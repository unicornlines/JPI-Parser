"""Minimal Click-based CLI: list flights and export CSV."""
from __future__ import annotations

from typing import List, Optional, Sequence

import click

from jpi_analyzer.decoder import DecodedFlight, FlightDecoder
from jpi_analyzer.exporter import export_flights_csv
from jpi_analyzer.parser import JpiFile


@click.group()
@click.option("--file", "-f", "file_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to a .JPI file.")
@click.pass_context
def main(ctx: click.Context, file_path: str) -> None:
    """Parse a JPI EDM file and export flights to CSV."""
    ctx.ensure_object(dict)
    ctx.obj["file_path"] = file_path


@main.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """Print file metadata and a one-line summary per flight."""
    jpi = JpiFile.open(ctx.obj["file_path"])
    click.echo(f"File:           {jpi.path}")
    click.echo(f"Tail / serial:  {jpi.tail_number}")
    click.echo(f"Model:          EDM{jpi.model}  sw={jpi.sw_version}  "
               f"build={jpi.build_num}  proto={jpi.protocol_id}")
    click.echo(f"Created:        {jpi.file_created_at}")
    click.echo(f"Eng/OAT temp:   {jpi.eng_deg} / {jpi.oat_deg}")
    click.echo(f"Flights:        {len(jpi.flights)}")
    click.echo("")
    for fid, fr in jpi.flights.items():
        df = FlightDecoder(jpi, fr).decode()
        click.echo(f"  #{fid:5d}  start={df.start_datetime}  "
                   f"records={df.n_records:5d}  "
                   f"duration={df.duration}  valid={df.valid}")


@main.command()
@click.option("--flights", "-F", "flight_spec", default="all",
              help="Flights to include: 'all' or comma-separated IDs (e.g. '1224,1225').")
@click.option("--metrics", "-m", "metric_spec", default="all",
              help="Metric codes: 'all' or comma-separated (e.g. 'E1,C1,MAP,RPM').")
@click.option("--out-dir", "-o", default="./jpi_csv",
              type=click.Path(file_okay=False),
              help="Directory to write CSVs into.")
@click.pass_context
def csv(ctx: click.Context, flight_spec: str, metric_spec: str, out_dir: str) -> None:
    """Export flights to CSV (one file per flight)."""
    jpi = JpiFile.open(ctx.obj["file_path"])
    fids = _resolve_flights(jpi, flight_spec)
    flights = [FlightDecoder(jpi, jpi.get_flight(f)).decode() for f in fids]
    available = _common_metrics(flights)
    metrics = _resolve_metrics(metric_spec, available)
    paths = export_flights_csv(flights, out_dir, metrics)
    click.echo(f"Wrote {len(paths)} files to {out_dir}:")
    for p in paths:
        click.echo(f"  {p}")


def _resolve_flights(jpi: JpiFile, spec: str) -> List[int]:
    spec = spec.strip().lower()
    if spec in ("all", "*"):
        return list(jpi.flights.keys())
    out: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            fid = int(part)
        except ValueError:
            raise click.BadParameter(f"Bad flight id: {part!r}")
        if fid not in jpi.flights:
            raise click.BadParameter(f"Flight {fid} not in file (have {list(jpi.flights)})")
        out.append(fid)
    return out


def _resolve_metrics(spec: str, available: Sequence[str]) -> List[str]:
    spec = spec.strip().lower()
    if spec in ("all", "*"):
        return list(available)
    out: List[str] = []
    for part in spec.split(","):
        code = part.strip().upper()
        if not code:
            continue
        if code not in available:
            raise click.BadParameter(
                f"Unknown metric {code!r}; available: {', '.join(available)}")
        out.append(code)
    return out


def _common_metrics(flights: Sequence[DecodedFlight]) -> List[str]:
    seen: List[str] = []
    for f in flights:
        for c in f.available_codes:
            if c not in seen:
                seen.append(c)
    return seen


if __name__ == "__main__":
    main(obj={})
