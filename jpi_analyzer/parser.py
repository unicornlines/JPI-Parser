"""Parse the JPI EDM file header and locate per-flight binary blocks."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


class HeaderNotFoundError(Exception):
    pass


@dataclass
class FlightRecord:
    """A flight as advertised in the file header — locator only, not yet decoded."""
    id: int
    size: int                          # byte length of this flight's data block
    start: Optional[int] = None        # absolute byte offset to flight payload
    found: bool = False
    data: Optional[bytes] = None       # raw bytes for the flight (filled after locate)


@dataclass
class JpiFile:
    path: str
    raw: bytes = b""
    header_offset: int = 0
    flight_data_start: int = 0
    flights: Dict[int, FlightRecord] = field(default_factory=dict)
    tail_number: str = ""
    model: str = ""
    sw_version: int = 0
    build_num: str = ""
    beta_num: str = ""
    protocol_id: int = 0
    edm_typ: bool = False              # True for EDM>=900 — drives 16-bit vs 8-bit data records
    twin_flag: bool = False
    fuel_unit: int = 0                 # 0 = gallons, 1 = liters
    eng_deg: str = "F"
    oat_deg: str = "F"
    cfg_high_byte: int = 0
    cfg_low_byte: int = 0
    egt_limit: int = 0
    cht_limit: int = 0
    cht_low: int = 0
    bat_limit: float = 0.0
    oil_limit: int = 0
    file_created_at: Optional[datetime] = None
    created_with: str = "N/A"

    @classmethod
    def open(cls, path: str) -> "JpiFile":
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        with open(path, "rb") as fh:
            raw = fh.read()
        if not raw:
            raise ValueError("Empty JPI file")
        f = cls(path=path, raw=raw)
        f._locate_header()
        f._parse_dollar_records()
        f._extract_version()
        f._locate_flights()
        return f

    # ---------- header & metadata ----------

    def _locate_header(self) -> None:
        # JPI files sometimes have leading zero-padding before the "$U" magic.
        m = re.search(rb"\$U", self.raw)
        if m is None:
            raise HeaderNotFoundError("'$U' magic not found")
        self.header_offset = m.start()

    def _read_dollar_block(self, ptr: int) -> tuple[str, int]:
        """Read characters until '*' (skipping NUL bytes), return (text, new_ptr)."""
        text = []
        while ptr < len(self.raw):
            ch = self.raw[ptr]
            if ch == 0x2A:  # '*'
                return "".join(text), ptr
            if ch != 0:
                text.append(chr(ch))
            ptr += 1
        return "".join(text), ptr

    def _parse_dollar_records(self) -> None:
        ptr = self.header_offset
        block_skip = 5  # past '*XX\r\n'
        while ptr < len(self.raw):
            text, star_pos = self._read_dollar_block(ptr)
            if star_pos >= len(self.raw):
                break
            fields = text.split(",")
            kind = fields[0]
            if kind == "$U" and len(fields) >= 2:
                self.tail_number = fields[1].strip()
            elif kind == "$T" and len(fields) >= 7:
                try:
                    month = int(fields[1])
                    day = int(fields[2])
                    yy = int(fields[3])
                    year = 2000 + yy if yy < 75 else 1900 + yy
                    hour = int(fields[4])
                    minute = int(fields[5])
                    secs_milli = int(fields[6])
                    secs = secs_milli // 1000
                    millis = secs_milli % 1000
                    self.file_created_at = datetime(
                        year, month, day, hour, minute, secs, millis * 1000)
                except (ValueError, IndexError):
                    pass
            elif kind == "$C" and len(fields) >= 2:
                self.model = fields[1].strip()
                # The build/beta layout depends on field count.
                idx = len(fields) - 1
                try:
                    if idx in (8, 9):
                        self.build_num = fields[idx - 1].strip()
                        self.beta_num = fields[idx].strip()
                        self.sw_version = int(fields[idx - 2].strip() or 0)
                    else:
                        self.sw_version = int(fields[idx].strip() or 0)
                except ValueError:
                    pass
                try:
                    cfg_num = round(float(fields[2]))
                    hex_str = format(cfg_num, "X").rjust(2, "0")
                    self.cfg_high_byte = int(hex_str[:-2] or "0", 16)
                    self.cfg_low_byte = int(hex_str[-2:], 16)
                except (ValueError, IndexError):
                    pass
                try:
                    self.eng_deg = "F" if (int(fields[3]) & 4096) else "C"
                except (ValueError, IndexError):
                    pass
                try:
                    self.oat_deg = "F" if (int(fields[5]) & 8192) else "C"
                except (ValueError, IndexError):
                    pass
                # Edm_Typ flips to True for >=900-series, False for 830/etc.
                try:
                    self.edm_typ = float(self.model) >= 900.0
                except ValueError:
                    self.edm_typ = False
                self.twin_flag = self.model in ("760", "790")
            elif kind == "$P" and len(fields) >= 2:
                try:
                    self.protocol_id = round(float(fields[1]))
                except ValueError:
                    pass
                # JPI's reference decoder unconditionally flips Edm_Typ on at $P;
                # the order of $C vs $P in the file determines the final value.
                self.edm_typ = True
            elif kind == "$F" and len(fields) >= 2:
                try:
                    self.fuel_unit = int(fields[1])
                except ValueError:
                    pass
            elif kind == "$A" and len(fields) >= 8:
                # $A, fixed?, bat*10, ?, cht_limit, cht_low, egt_limit, oil_limit
                try:
                    self.bat_limit = int(fields[2]) * 0.1
                    self.cht_limit = int(fields[4])
                    self.cht_low = int(fields[5])
                    self.egt_limit = int(fields[6])
                    self.oil_limit = int(fields[7])
                except (ValueError, IndexError):
                    pass
            elif kind == "$D" and len(fields) >= 3:
                try:
                    fid = int(fields[1])
                    fsize = int(fields[2]) * 2
                    self.flights[fid] = FlightRecord(id=fid, size=fsize)
                except ValueError:
                    pass
            elif kind == "$L":
                # End of dollar-record header: data follows the trailing block_skip bytes
                self.flight_data_start = star_pos + block_skip
                return
            ptr = star_pos + block_skip

    def _extract_version(self) -> None:
        tail = self.raw[-200:]
        m = re.search(rb"\$V[^\r\n]*", tail)
        if not m:
            return
        text = m.group(0).decode("latin-1", errors="ignore").strip()
        # Format example: "$V Created by EDM830 VER 252 BLD 64 BETA 0*5C"
        match = re.search(
            r"Created by (?P<dev>\w+)\s+VER\s+(?P<ver>[0-9.]+)\s+BLD\s+(?P<bld>\d+)\s+BETA\s+(?P<beta>\d+)",
            text,
        )
        if match:
            self.created_with = match.group(0)
            if not self.build_num or self.build_num == "-1":
                self.build_num = match.group("bld")
            if not self.beta_num or self.beta_num == "-1":
                self.beta_num = match.group("beta")

    # ---------- flight locator ----------

    def _read_be_word(self, offset: int) -> int:
        if offset + 1 >= len(self.raw):
            return -1
        return (self.raw[offset] << 8) | self.raw[offset + 1]

    def _locate_flights(self) -> None:
        """Find each flight's start offset and copy its raw bytes.

        Each flight begins with its 16-bit big-endian flight ID. Sizes from $D
        records are advisory — JPI sometimes pads with an off-by-one byte, so
        we scan a small window when the expected ID isn't where we predicted.
        """
        ptr = self.flight_data_start
        for fid in list(self.flights.keys()):
            rec = self.flights[fid]
            size = rec.size
            additional = 0
            if self._read_be_word(ptr) == fid:
                rec.found = True
            elif self._read_be_word(ptr - 1) == fid:
                additional = -1
                rec.found = True
            else:
                # Wider scan window
                for delta in range(-30, 31):
                    if self._read_be_word(ptr + delta) == fid:
                        additional = delta
                        rec.found = True
                        break
            ptr += additional
            rec.start = ptr
            end = min(ptr + size, len(self.raw))
            rec.data = bytes(self.raw[ptr:end])
            ptr += size

    # ---------- helpers ----------

    @property
    def flight_ids(self) -> List[int]:
        return list(self.flights.keys())

    def get_flight(self, fid: int) -> FlightRecord:
        if fid not in self.flights:
            raise KeyError(f"Flight {fid} not in file")
        return self.flights[fid]
