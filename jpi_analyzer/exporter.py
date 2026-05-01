"""Export decoded flights to CSV."""
from __future__ import annotations

import csv
import os
from typing import Iterable, List, Optional, Sequence

from jpi_analyzer.decoder import DecodedFlight


def _fmt_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:.2f}"
    return str(v)


def export_flight_csv(
    flight: DecodedFlight,
    path: str,
    metrics: Optional[Sequence[str]] = None,
) -> None:
    """Write one flight to a CSV at `path`. Columns: datetime + chosen metrics."""
    if metrics is None:
        metrics = flight.available_codes
    metrics = [m for m in metrics if m in flight.series]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["datetime"] + list(metrics))
        for i, ts in enumerate(flight.timestamps):
            row = [ts.isoformat() if ts else ""]
            for code in metrics:
                row.append(_fmt_value(flight.series[code][i]))
            w.writerow(row)


def export_flights_csv(
    flights: Iterable[DecodedFlight],
    out_dir: str,
    metrics: Optional[Sequence[str]] = None,
    file_pattern: str = "flight_{flight_id}.csv",
) -> List[str]:
    """Write one CSV per flight into `out_dir`. Returns the list of created paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []
    for flight in flights:
        if not flight.valid:
            continue
        p = os.path.join(out_dir, file_pattern.format(flight_id=flight.flight_id))
        chosen = list(metrics) if metrics is not None else flight.available_codes
        export_flight_csv(flight, p, chosen)
        paths.append(p)
    return paths
