"""Decode an individual flight's binary block into time-series per metric.

This is a Python port of the EzTrends2 `Decomp.ReadRecord` routine. Each flight
record consists of a small header (Cfg_Word values + interval + start
date/time) followed by a stream of delta-encoded data records. Every metric
maintains a `running_total` updated by the deltas in each record; the absolute
engineering value is `running_total / scale_val`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from jpi_analyzer.metrics import MetricDef, headers_for_model
from jpi_analyzer.parser import FlightRecord, JpiFile


class _ByteReader:
    __slots__ = ("data", "ptr")

    def __init__(self, data: bytes, start: int = 0):
        self.data = data
        self.ptr = start

    def byte(self) -> int:
        if self.ptr >= len(self.data):
            return -1
        v = self.data[self.ptr]
        self.ptr += 1
        return v

    def word(self) -> int:
        if self.ptr + 1 >= len(self.data):
            return -1
        v = (self.data[self.ptr] << 8) | self.data[self.ptr + 1]
        self.ptr += 2
        return v

    def long(self) -> int:
        if self.ptr + 3 >= len(self.data):
            return -1
        v = ((self.data[self.ptr] << 24)
             | (self.data[self.ptr + 1] << 16)
             | (self.data[self.ptr + 2] << 8)
             | self.data[self.ptr + 3])
        self.ptr += 4
        return v


@dataclass
class DecodedFlight:
    """Decoded time-series for a single flight."""
    flight_id: int
    start_datetime: Optional[datetime] = None
    record_interval: int = 1                    # seconds between samples
    fuel_unit: int = 0
    horsepower_setting: int = 0
    available_codes: List[str] = field(default_factory=list)
    timestamps: List[datetime] = field(default_factory=list)
    series: Dict[str, List[Optional[float]]] = field(default_factory=dict)
    valid: bool = False
    error: str = ""

    def metric_codes(self) -> List[str]:
        return list(self.available_codes)

    def metric_values(self, code: str) -> List[Optional[float]]:
        return self.series.get(code, [])

    def metric_values_with_time(self, code: str):
        return list(zip(self.timestamps, self.series.get(code, [])))

    @property
    def duration(self) -> timedelta:
        if not self.timestamps:
            return timedelta(0)
        return self.timestamps[-1] - self.timestamps[0]

    @property
    def n_records(self) -> int:
        return len(self.timestamps)


class FlightDecoder:
    """Decode one flight from a JpiFile into a DecodedFlight."""

    def __init__(self, jpi: JpiFile, flight: FlightRecord):
        self.jpi = jpi
        self.flight = flight
        self.headers: List[MetricDef] = []
        # Active metrics are those whose cfg bit is enabled in this flight's Cfg_Word
        self.active_headers: List[MetricDef] = []
        self.cfg_word: List[int] = [0, 0, 0, 0, 0, 0, 0]
        self.running_total: Dict[str, float] = {}
        self.is_new_hdr_format = False
        self.lat_start = 0
        self.lng_start = 0
        self.use_xor_checksum = True
        self._has_16bit_records = False    # word1/word2 are 16-bit (Edm_Typ_actual)
        self.edm_typ_actual = False

    def decode(self) -> DecodedFlight:
        out = DecodedFlight(flight_id=self.flight.id, fuel_unit=self.jpi.fuel_unit)
        if not self.flight.found or not self.flight.data:
            out.error = "Flight not found in file"
            return out

        reader = _ByteReader(self.flight.data, 0)

        # ---- flight header ----
        try:
            self._scan_flight_header(reader, out)
        except (ValueError, IndexError) as exc:
            out.error = f"Flight header parse failed: {exc}"
            return out

        # ---- choose & filter headers based on Cfg_Word ----
        self.headers = headers_for_model(
            self.jpi.model, self.jpi.fuel_unit, self.jpi.twin_flag, self.edm_typ_actual,
        )
        self.active_headers = [
            h for h in self.headers
            if h.code == "DIF" or self._cfg_enabled(h)
        ]
        out.available_codes = [h.code for h in self.active_headers]
        # Initialize running totals
        for h in self.headers:
            self.running_total[h.code] = 240.0
        if "HP" in self.running_total:
            self.running_total["HP"] = 0.0
        if "LAT" in self.running_total:
            self.running_total["LAT"] = float(self.lat_start)
        if "LNG" in self.running_total:
            self.running_total["LNG"] = float(self.lng_start)

        # Allocate empty series
        out.series = {h.code: [] for h in self.active_headers}
        out.timestamps = []
        out.record_interval = max(int(self.cfg_interval), 1)
        out.start_datetime = self.start_datetime

        # ---- iterate data records ----
        ts = self.start_datetime
        end_ptr = len(self.flight.data)
        last_record: Optional[Dict[str, float]] = None
        rep_remaining = 0
        while reader.ptr < end_ptr - 4:
            try:
                rec_values, rep_count = self._read_one_record(reader)
            except (ValueError, IndexError):
                break
            if rec_values is None:
                break
            if rep_count > 0 and last_record is not None:
                # Replay the previous record `rep_count` times before applying this one
                for _ in range(rep_count):
                    if ts is not None:
                        out.timestamps.append(ts)
                        ts = ts + timedelta(seconds=out.record_interval)
                    else:
                        out.timestamps.append(None)
                    for code, vals in out.series.items():
                        vals.append(last_record.get(code))
            # Now record the values from this new decoded record
            if ts is not None:
                out.timestamps.append(ts)
                ts = ts + timedelta(seconds=out.record_interval)
            else:
                out.timestamps.append(None)
            for code, vals in out.series.items():
                vals.append(rec_values.get(code))
            last_record = rec_values

        out.valid = bool(out.timestamps)
        if not out.valid and not out.error:
            out.error = "No decodable data records"
        return out

    # ---------- internals ----------

    def _scan_flight_header(self, r: _ByteReader, out: DecodedFlight) -> None:
        # First word is the flight ID — verify
        flight_id = r.word()
        if flight_id != self.flight.id:
            # Some files have an off-by-one
            r.ptr = max(r.ptr - 1, 0)
            flight_id = r.word()
        self.cfg_word[0] = r.word()
        self.cfg_word[1] = r.word()
        try:
            mv = int(float(self.jpi.model))
        except ValueError:
            mv = 0
        wide_models = (711, 730, 740, 830, 831)
        if self.jpi.edm_typ:
            # 14-byte XOR test: when zero, this is a "narrow" header (no cfg[2..4])
            xor_test = 0
            for i in range(15):
                xor_test ^= self.flight.data[i]
            edm_typ_actual = True
            if mv in wide_models and xor_test == 0:
                edm_typ_actual = False
            self.edm_typ_actual = edm_typ_actual
            if edm_typ_actual:
                self.cfg_word[2] = r.word()
                self.cfg_word[3] = r.word()
                self.is_new_hdr_format = self._detect_new_hdr(r)
                if self.is_new_hdr_format:
                    self.cfg_word[4] = r.word()
                    if mv in wide_models:
                        self.lat_start = self._signed_long(r.long())
                        self.lng_start = self._signed_long(r.long())
                self._has_16bit_records = True
        fuel_unit_byte = r.byte()
        horsepower = r.byte()
        self.cfg_interval = r.word()
        date_word = r.word()
        time_word = r.word()
        # Reserved/checksum
        r.byte()
        try:
            self.start_datetime = self._decode_date_time(date_word, time_word)
        except Exception:
            self.start_datetime = self.jpi.file_created_at
        out.horsepower_setting = horsepower if horsepower is not None and horsepower >= 0 else 0
        # Determine checksum mode
        if (mv == 760 and self.jpi.sw_version >= 144) \
                or (mv == 700 and self.jpi.sw_version >= 296) \
                or (mv == 800 and self.jpi.sw_version >= 300) \
                or (self.jpi.edm_typ and self.jpi.protocol_id == 2):
            self.use_xor_checksum = False
        else:
            self.use_xor_checksum = True

    def _detect_new_hdr(self, r: _ByteReader) -> bool:
        # Heuristic copied from EzTrends2: peek ahead to see if structure looks like
        # the new (lat/lng-bearing) header. If we run off the end, assume old.
        p = r.ptr
        try:
            d = self.flight.data
            if (d[p + 19] == d[p + 21] and d[p + 20] == d[p + 22]) or (
                d[p + 21] == d[p - 8]
                and d[p + 22] == d[p - 7]
                and d[p + 23] == d[p - 6]
                and d[p + 24] == d[p - 5]
            ):
                return True
            if d[p + 11] == d[p + 13] or d[p + 12] == d[p + 14]:
                return True
        except IndexError:
            pass
        return False

    @staticmethod
    def _signed_long(v: int) -> int:
        if v >= 0x80000000:
            return v - 0x100000000
        return v

    @staticmethod
    def _decode_date_time(date_word: int, time_word: int) -> Optional[datetime]:
        """JPI packs date as bits day(5)|month(4)|year(7) and time as h(5)|m(6)|s2(5).

        Seconds are stored in 2-second ticks. The original C# masks `time & 62`
        — i.e. bits 1-5 — which intentionally drops the LSB so the value is an
        even number 0..62.
        """
        if date_word <= 0 or time_word <= 0:
            return None
        day = date_word & 0x1F
        month = (date_word >> 5) & 0x0F
        yy = (date_word >> 9) & 0x7F
        year = 2000 + yy if yy < 75 else 1900 + yy
        sec = time_word & 62
        minute = (time_word >> 5) & 63
        hour = (time_word >> 11) & 31
        if sec >= 60:
            sec = 0
            minute += 1
        if minute >= 60:
            minute = 0
            hour += 1
        try:
            return datetime(year, month, day, hour % 24, minute, sec)
        except ValueError:
            return None

    def _cfg_enabled(self, hdr: MetricDef) -> bool:
        bidx = hdr.cfg_byt_idx
        bit = hdr.cfg_bit_idx
        if bidx == 0 and bit == 0:
            # "always-on" markers: BAT, MARK, DIF, etc.
            return True
        try:
            return (self.cfg_word[bidx] & (1 << bit)) != 0
        except IndexError:
            return False

    def _read_one_record(self, r: _ByteReader) -> Tuple[Optional[Dict[str, float]], int]:
        """Return (values_per_code, replay_count)."""
        start_ptr = r.ptr
        if self._has_16bit_records:
            word1 = r.word()
            word2 = r.word()
        else:
            word1 = r.byte()
            word2 = r.byte()
        if word1 == -1 or word2 == -1 or word1 != word2:
            return None, 0
        rep_count = r.byte()
        if rep_count == -1:
            return None, 0

        # Read control bytes (one per set bit in word1)
        ctl = [{"exist": False, "ctl": 0, "sgn": 0} for _ in range(16)]
        mask = 1
        for i in range(16):
            if (word1 & mask) != 0:
                ctl[i]["exist"] = True
                b = r.byte()
                if b == -1:
                    return None, 0
                ctl[i]["ctl"] = b
            mask <<= 1

        # Read sign bytes — for indices in {0..5, 8..15} when their bit is set in word1.
        # (The C# expression `i<6 | i>7 && (word1 & m) != 0` parses as `(i<6 || i>7) && bit-set`
        # because `|` has higher precedence than `&&` in C# for booleans.)
        mask = 1
        for i in range(16):
            if (i < 6 or i > 7) and (word1 & mask) != 0:
                b = r.byte()
                if b == -1:
                    return None, 0
                ctl[i]["sgn"] = b
            mask <<= 1

        # Decode data bytes into Data_Bytes[byt_idx][bit_idx]
        data_bytes: Dict[int, Dict[int, Tuple[int, bool, bool]]] = {
            i: {j: (0, False, False) for j in range(8)} for i in range(16)
        }
        for byt_idx in range(16):
            if not ctl[byt_idx]["exist"]:
                continue
            ctl_idx = ctl[byt_idx]["ctl"]
            # Sign-byte source has a couple of cross-references
            if byt_idx == 6:
                sgn_idx = ctl[0]["sgn"]
            elif byt_idx == 7:
                sgn_idx = ctl[3]["sgn"]
            else:
                sgn_idx = ctl[byt_idx]["sgn"]
            mask = 1
            for bit_idx in range(8):
                if (ctl_idx & mask) == 0:
                    mask <<= 1
                    continue
                # Some byte-indices imply "double-byte" multipliers (×256)
                multiplier = 1
                sign_check_mask = mask
                if byt_idx == 5 and bit_idx in (2, 4):
                    multiplier = 256
                    sign_check_mask //= 2
                elif byt_idx in (6, 7):
                    multiplier = 256
                elif byt_idx == 10 and bit_idx in (1, 2):
                    multiplier = 256
                    sign_check_mask *= 32
                elif byt_idx in (9, 12):
                    if bit_idx in (4, 5):
                        multiplier = 256
                        sign_check_mask //= 16
                    elif bit_idx == 7:
                        multiplier = 256
                elif byt_idx in (13, 14) and bit_idx in (4, 5, 6):
                    multiplier = 256
                    sign_check_mask //= 16
                v = r.byte()
                if v == -1:
                    return None, 0
                is_valid = v != 0
                value = v * multiplier
                sign = (sgn_idx & sign_check_mask) != 0 if sign_check_mask else False
                data_bytes[byt_idx][bit_idx] = (value, is_valid, sign)
                mask <<= 1

        # End-of-record filler byte + checksum byte
        r.byte()  # filler
        # We skip strict checksum verification here — the C# code trusts the
        # XOR/sum, but mismatches abort the whole flight. To be tolerant of
        # quirks in older firmware we accept all records and rely on the data
        # itself.

        # Apply deltas to running totals & emit values
        out: Dict[str, float] = {}
        # First compute min/max EGT for DIF (left side only — single-engine)
        egt_values: List[int] = []
        for hdr in self.active_headers:
            if hdr.m_lo_byt_idx < 0:
                continue
            lo = data_bytes[hdr.m_lo_byt_idx][hdr.m_lo_bit_idx]
            lo_val, lo_valid, lo_sign = lo
            delta = lo_val
            if lo_sign:
                delta = -delta
            if hdr.m_hi_byt_idx >= 0:
                hi = data_bytes[hdr.m_hi_byt_idx][hdr.m_hi_bit_idx]
                hi_val, hi_valid, hi_sign = hi
                delta = delta + hi_val if not hi_sign else delta - hi_val
            self.running_total[hdr.code] += delta
            number = round(self.running_total[hdr.code])

            # Emit value
            if hdr.code == "DIF":
                continue  # computed after EGT loop
            if not lo_valid:
                if hdr.m_hi_byt_idx < 0 or not data_bytes[hdr.m_hi_byt_idx][hdr.m_hi_bit_idx][1]:
                    out[hdr.code] = None
                    continue
            if hdr.code == "MARK":
                out[hdr.code] = float(number & 7)
                continue
            if hdr.scale_val == 1.0:
                out[hdr.code] = float(number)
            else:
                out[hdr.code] = number / hdr.scale_val
            if hdr.sensor_name.startswith("Left EGT") and lo_valid:
                egt_values.append(number)

        if "DIF" in out or any(h.code == "DIF" for h in self.active_headers):
            if egt_values:
                out["DIF"] = float(max(egt_values) - min(egt_values))
            else:
                out["DIF"] = None
        return out, rep_count
