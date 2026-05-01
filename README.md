# JPI Parser

Python library and CLI for parsing flight-data files written by JP Instruments
engine monitors (EDM830 and other protocol-2 devices).

The repository also publishes [`filespec.md`](filespec.md) — a written-up
description of the binary file format, derived from observation of files
produced by the device.

## Install

```bash
pip install -e .
```

This exposes two equivalent console commands: `jpi-analyzer` and `jpia`.

## CLI

```bash
# File metadata + flight list
jpia --file data.JPI info

# Export selected flights & metrics to CSV (one file per flight)
jpia --file data.JPI csv --flights all --metrics all --out-dir ./out
jpia --file data.JPI csv --flights 1224,1225 --metrics E1,C1,MAP,RPM,FF --out-dir ./out
```

## Library

```python
from jpi_analyzer import JpiFile, FlightDecoder, export_flight_csv

jpi = JpiFile.open("data.JPI")
flight = FlightDecoder(jpi, jpi.get_flight(1224)).decode()
export_flight_csv(flight, "1224.csv")
```

## Repository layout

| Path | Purpose |
|------|---------|
| `jpi_analyzer/` | The package — parser, decoder, CSV exporter, CLI. |
| `filespec.md` | Description of the JPI EDM830 file format. |
| `pyproject.toml` | Package manifest. |

