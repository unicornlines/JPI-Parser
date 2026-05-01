"""Metric definitions: units, scale, axis ranges per metric type.

Axis ranges chosen to span the typical operating envelope of piston/turbine GA
engines plus headroom. They are *recommended* defaults; callers can override.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class MetricCategory:
    name: str
    unit: str
    axis_min: float
    axis_max: float
    description: str = ""


# Keyed by metric short code prefix. EGT covers E1..E9, LE1..LE9, RE1..RE9 etc.
# CHT covers C1..C9, etc.
CATEGORIES: Dict[str, MetricCategory] = {
    "EGT": MetricCategory("EGT", "°F", 0, 2000, "Exhaust Gas Temperature"),
    "CHT": MetricCategory("CHT", "°F", 0, 500, "Cylinder Head Temperature"),
    "TIT": MetricCategory("TIT", "°F", 0, 2000, "Turbine Inlet Temperature"),
    "ITT": MetricCategory("ITT", "°F", 0, 2000, "Inter-Turbine Temperature"),
    "OAT": MetricCategory("OAT", "°F", -60, 130, "Outside Air Temperature"),
    "OILT": MetricCategory("OILT", "°F", 0, 300, "Oil Temperature"),
    "OILP": MetricCategory("OILP", "PSI", 0, 100, "Oil Pressure"),
    "CDT": MetricCategory("CDT", "°F", 0, 400, "Compressor Discharge Temp"),
    "IAT": MetricCategory("IAT", "°F", 0, 200, "Induction Air Temperature"),
    "CLD": MetricCategory("CLD", "°F/min", -100, 100, "Cylinder Cooling Rate"),
    "DIF": MetricCategory("DIF", "°F", 0, 300, "EGT Spread (max-min)"),
    "MAP": MetricCategory("MAP", "in.Hg", 0, 35, "Manifold Pressure"),
    "RPM": MetricCategory("RPM", "rpm", 0, 3500, "Engine RPM"),
    "FF": MetricCategory("FF", "GPH", 0, 30, "Fuel Flow"),
    "FF2": MetricCategory("FF2", "GPH", 0, 30, "Fuel Flow #2"),
    "USD": MetricCategory("USD", "gal", 0, 200, "Fuel Used"),
    "USD2": MetricCategory("USD2", "gal", 0, 200, "Fuel Used #2"),
    "FL": MetricCategory("FL", "gal", 0, 100, "Fuel Level"),
    "FP": MetricCategory("FP", "PSI", 0, 60, "Fuel Pressure"),
    "BAT": MetricCategory("BAT", "V", 0, 16, "Battery Voltage"),
    "BAT2": MetricCategory("BAT2", "V", 0, 16, "Battery #2 Voltage"),
    "AMP": MetricCategory("AMP", "A", -100, 100, "Amperage"),
    "AMP2": MetricCategory("AMP2", "A", -100, 100, "Amperage #2"),
    "HP": MetricCategory("HP", "%", 0, 110, "Percent Power / Horsepower"),
    "HRS": MetricCategory("HRS", "h", 0, 10000, "Hobbs Hours"),
    "MARK": MetricCategory("MARK", "", 0, 8, "Pilot Mark / Lean-Find State"),
    "SPD": MetricCategory("SPD", "kt", 0, 300, "Ground Speed"),
    "ALT": MetricCategory("ALT", "ft", -1000, 30000, "Pressure Altitude"),
    "LAT": MetricCategory("LAT", "deg", -90, 90, "Latitude"),
    "LNG": MetricCategory("LNG", "deg", -180, 180, "Longitude"),
    "NG": MetricCategory("NG", "%", 0, 110, "Gas Generator Speed"),
    "NP": MetricCategory("NP", "rpm", 0, 3000, "Propeller Speed"),
    "TRQ": MetricCategory("TRQ", "%", 0, 110, "Torque"),
    "HYD": MetricCategory("HYD", "PSI", 0, 5000, "Hydraulic Pressure"),
}


def _category_for_code(code: str) -> Optional[MetricCategory]:
    """Strip L/R prefix and trailing digit to find category."""
    base = code
    if base.startswith(("L", "R")) and base[1:] in CATEGORIES:
        return CATEGORIES[base[1:]]
    # Strip trailing digit(s): "E1" -> "E", "RC1" -> "RC"
    stripped = base.rstrip("0123456789")
    # Single-letter codes for cylinders: E (EGT), C (CHT), T (TIT)
    letter_map = {"E": "EGT", "C": "CHT", "T": "TIT", "LE": "EGT",
                  "RE": "EGT", "LC": "CHT", "RC": "CHT", "LT": "TIT",
                  "RT": "TIT"}
    if stripped in letter_map:
        return CATEGORIES[letter_map[stripped]]
    if stripped in CATEGORIES:
        return CATEGORIES[stripped]
    # Strip an L/R prefix and try again: "LMAP" -> "MAP"
    if stripped.startswith(("L", "R")) and stripped[1:] in CATEGORIES:
        return CATEGORIES[stripped[1:]]
    return None


@dataclass(frozen=True)
class MetricDef:
    """Definition of one decodable metric in a flight record."""
    sensor_name: str          # "Left EGT 1"
    code: str                 # "E1", "MAP", "RPM"
    cfg_byt_idx: int          # which Cfg_Word to test
    cfg_bit_idx: int          # which bit
    scale_val: float          # divisor for engineering units
    m_lo_byt_idx: int = -1    # byte index in data stream (low delta)
    m_lo_bit_idx: int = -1
    m_hi_byt_idx: int = -1    # byte index in data stream (high delta)
    m_hi_bit_idx: int = -1

    @property
    def category(self) -> Optional[MetricCategory]:
        return _category_for_code(self.code)

    @property
    def unit(self) -> str:
        cat = self.category
        return cat.unit if cat else ""


def axis_range_for(code: str) -> Tuple[float, float]:
    """Recommended (min, max) Y-axis range for a metric short code."""
    cat = _category_for_code(code)
    if cat is None:
        return (0.0, 100.0)
    return (cat.axis_min, cat.axis_max)


def unit_for(code: str) -> str:
    cat = _category_for_code(code)
    return cat.unit if cat else ""


def description_for(code: str) -> str:
    cat = _category_for_code(code)
    return cat.description if cat else code


def _h(name, cfg_b, cfg_bit, code, scale=1.0, lo_b=-1, lo_bit=-1, hi_b=-1, hi_bit=-1):
    return MetricDef(name, code, cfg_b, cfg_bit, scale, lo_b, lo_bit, hi_b, hi_bit)


# ---- Header tables, transcribed from EzTrends2 Decomp.cs ----
# init_strings_for_107 — used for EDM830/831 (and other models) running protocol 2.
# Includes byte indices up to 10 (HRS, AMP, FL, ALT, SPD, LAT, LNG).
HEADERS_107 = [
    _h("Left EGT 1", 0, 2, "E1", 1, 0, 0, 6, 0),
    _h("Left EGT 2", 0, 3, "E2", 1, 0, 1, 6, 1),
    _h("Left EGT 3", 0, 4, "E3", 1, 0, 2, 6, 2),
    _h("Left EGT 4", 0, 5, "E4", 1, 0, 3, 6, 3),
    _h("Left EGT 5", 0, 6, "E5", 1, 0, 4, 6, 4),
    _h("Left EGT 6", 0, 7, "E6", 1, 0, 5, 6, 5),
    _h("Left EGT 7", 0, 8, "E7", 1, 3, 0, 7, 0),
    _h("Left EGT 8", 0, 9, "E8", 1, 3, 1, 7, 1),
    _h("Left EGT 9", 0, 10, "E9", 1, 3, 2, 7, 2),
    _h("Left CHT 1", 0, 11, "C1", 1, 1, 0),
    _h("Left CHT 2", 0, 12, "C2", 1, 1, 1),
    _h("Left CHT 3", 0, 13, "C3", 1, 1, 2),
    _h("Left CHT 4", 0, 14, "C4", 1, 1, 3),
    _h("Left CHT 5", 0, 15, "C5", 1, 1, 4),
    _h("Left CHT 6", 1, 0, "C6", 1, 1, 5),
    _h("Left CHT 7", 1, 1, "C7", 1, 3, 3),
    _h("Left CHT 8", 1, 2, "C8", 1, 3, 4),
    _h("Left CHT 9", 1, 3, "C9", 1, 3, 5),
    _h("Left TIT 1", 1, 5, "T1", 1, 0, 6, 6, 6),
    _h("Left TIT 2", 1, 6, "T2", 1, 0, 7, 6, 7),
    _h("Left ITT", 3, 12, "ITT", 1, 9, 3),
    _h("OAT", 1, 9, "OAT", 1, 2, 5),
    _h("Left DIF", 0, 0, "DIF"),
    _h("Left CLD", 0, 0, "CLD", 1, 1, 6),
    _h("Left CDT", 1, 7, "CDT", 1, 2, 2),
    _h("Left IAT", 1, 8, "IAT", 1, 2, 3),
    _h("Left MAP", 1, 14, "MAP", 10.0, 5, 0),
    _h("Left RPM", 1, 10, "RPM", 1, 5, 1, 5, 2),
    _h("Left HP", 1, 10, "HP", 1, 3, 6),
    _h("Left FF (gph)", 1, 11, "FF", 10.0, 2, 7),
    _h("Left FF (lph)", 1, 11, "FF_L", 1, 2, 7),
    _h("Left FF2 (gph)", 3, 5, "FF2", 10.0, 5, 6),
    _h("Left FF2 (lph)", 3, 5, "FF2_L", 1, 5, 6),
    _h("Left FP", 1, 15, "FP", 10.0, 8, 5),
    _h("Left TRQ", 3, 8, "TRQ", 1, 9, 2),
    _h("Left OILP", 1, 13, "OILP", 1, 2, 1),
    _h("Left OILT", 1, 4, "OILT", 1, 1, 7),
    _h("BAT", 0, 0, "BAT", 10.0, 2, 4),
    _h("BAT2", 2, 6, "BAT2", 10.0, 8, 1),
    _h("AMP", 0, 1, "AMP", 1, 8, 0),
    _h("AMP2", 2, 5, "AMP2", 1, 8, 2),
    _h("Left USD (gal)", 1, 11, "USD", 10.0, 2, 6),
    _h("Left USD (l)", 1, 11, "USD_L", 1, 2, 6),
    _h("Left FL (gal)", 2, 3, "RFL", 10.0, 8, 3),
    _h("Left FL (l)", 2, 3, "RFL_L", 1, 8, 3),
    _h("Left FL2 (gal)", 2, 4, "LFL", 10.0, 8, 4),
    _h("Left FL2 (l)", 2, 4, "LFL_L", 1, 8, 4),
    _h("Left HRS", 0, 0, "HRS", 10.0, 9, 6, 9, 7),
    _h("Left USD2 (gal)", 3, 5, "USD2", 10.0, 5, 7),
    _h("Left USD2 (l)", 3, 5, "USD2_L", 1, 5, 7),
    _h("Left HYD", 3, 15, "HYD", 1, 5, 5),
    _h("Left HYD2", 4, 2, "HYD2", 1, 5, 4),
    _h("SPD", 4, 5, "SPD", 1, 10, 5),
    _h("ALT", 4, 6, "ALT", 1, 10, 3),
    _h("LAT", 4, 3, "LAT", 1, 10, 7, 10, 2),
    _h("LNG", 4, 4, "LNG", 1, 10, 6, 10, 1),
    _h("MARK", 0, 0, "MARK", 1, 2, 0),
]

# init_strings_for_single — used for non-Edm_Typ_actual installations.
SINGLE_HEADERS = [
    _h("Left EGT 1", 0, 2, "E1", 1, 0, 0, 6, 0),
    _h("Left EGT 2", 0, 3, "E2", 1, 0, 1, 6, 1),
    _h("Left EGT 3", 0, 4, "E3", 1, 0, 2, 6, 2),
    _h("Left EGT 4", 0, 5, "E4", 1, 0, 3, 6, 3),
    _h("Left EGT 5", 0, 6, "E5", 1, 0, 4, 6, 4),
    _h("Left EGT 6", 0, 7, "E6", 1, 0, 5, 6, 5),
    _h("Left EGT 7", 0, 8, "E7", 1, 3, 0, 7, 0),
    _h("Left EGT 8", 0, 9, "E8", 1, 3, 1, 7, 1),
    _h("Left EGT 9", 0, 10, "E9", 1, 3, 2, 7, 2),
    _h("Left CHT 1", 0, 11, "C1", 1, 1, 0),
    _h("Left CHT 2", 0, 12, "C2", 1, 1, 1),
    _h("Left CHT 3", 0, 13, "C3", 1, 1, 2),
    _h("Left CHT 4", 0, 14, "C4", 1, 1, 3),
    _h("Left CHT 5", 0, 15, "C5", 1, 1, 4),
    _h("Left CHT 6", 1, 0, "C6", 1, 1, 5),
    _h("Left CHT 7", 1, 1, "C7", 1, 3, 3),
    _h("Left CHT 8", 1, 2, "C8", 1, 3, 4),
    _h("Left CHT 9", 1, 3, "C9", 1, 3, 5),
    _h("Left TIT 1", 1, 5, "T1", 1, 0, 6, 6, 6),
    _h("Left TIT 2", 1, 6, "T2", 1, 0, 7, 6, 7),
    _h("OAT", 1, 9, "OAT", 1, 2, 5),
    _h("Left DIF", 0, 0, "DIF"),
    _h("Left CLD", 0, 0, "CLD", 1, 1, 6),
    _h("Left CDT", 1, 7, "CDT", 1, 2, 2),
    _h("Left IAT", 1, 8, "IAT", 1, 2, 3),
    _h("Left MAP", 1, 14, "MAP", 10.0, 5, 0),
    _h("Left RPM", 1, 10, "RPM", 1, 5, 1, 5, 2),
    _h("Left HP", 1, 10, "HP", 1, 3, 6),
    _h("Left FF (gph)", 1, 11, "FF", 10.0, 2, 7),     # fUnit==0 default
    _h("Left FF (lph)", 1, 11, "FF_L", 1, 2, 7),       # fUnit==1
    _h("Left OILP", 1, 13, "OILP", 1, 2, 1),
    _h("Left OILT", 1, 4, "OILT", 1, 1, 7),
    _h("BAT", 0, 0, "BAT", 10.0, 2, 4),
    _h("Left USD (gal)", 1, 11, "USD", 10.0, 2, 6),
    _h("Left USD (l)", 1, 11, "USD_L", 1, 2, 6),
    _h("MARK", 0, 0, "MARK", 1, 2, 0),
]


# Codes that come in (gallons, liters) pairs. The "_L" variant uses scale 1.0,
# the bare variant uses scale 10.0. We pick one based on fUnit and rename to
# the bare code so downstream consumers see "FF" regardless of unit.
_FUEL_UNIT_PAIRS = {"FF", "FF2", "USD", "USD2", "RFL", "LFL"}


def headers_for_model(model: str, fuel_unit: int, twin: bool, edm_typ_actual: bool):
    """Return the list of MetricDef relevant for the model, with fUnit-conditional
    entries pruned. EDM830/831 with protocol-2 → HEADERS_107; otherwise SINGLE.
    """
    table = HEADERS_107 if edm_typ_actual else SINGLE_HEADERS
    out = []
    for hdr in table:
        bare = hdr.code[:-2] if hdr.code.endswith("_L") else hdr.code
        if bare in _FUEL_UNIT_PAIRS and bare != hdr.code:
            # liters variant — keep only when fuel_unit != 0
            if fuel_unit == 0:
                continue
        elif bare in _FUEL_UNIT_PAIRS and bare == hdr.code:
            # gallons variant — keep only when fuel_unit == 0
            if fuel_unit != 0:
                continue
        out.append(hdr)
    # Rename "_L" codes to their bare form
    normalized = []
    for h in out:
        if h.code.endswith("_L"):
            normalized.append(MetricDef(h.sensor_name, h.code[:-2], h.cfg_byt_idx,
                                        h.cfg_bit_idx, h.scale_val,
                                        h.m_lo_byt_idx, h.m_lo_bit_idx,
                                        h.m_hi_byt_idx, h.m_hi_bit_idx))
        else:
            normalized.append(h)
    return normalized


METRIC_LIBRARY = HEADERS_107
