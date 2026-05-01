# JPI `.JPI` File Format Specification

This document describes the binary file format produced by JP Instruments
Engine Data Monitors (EDM-series). The specification is anchored on the
EDM-830 product line.

> **Endianness.** All multi-byte integers in the binary sections are
> **big-endian** (high byte first). All ASCII text uses CRLF (`0x0D 0x0A`)
> line endings.

---

## 1. Top-level Layout

A `.JPI` file consists of four contiguous sections, in this fixed order:

| # | Section                | Encoding                | Marked by                        |
|---|------------------------|-------------------------|----------------------------------|
| 1 | ASCII Dollar Header    | ASCII / CRLF            | starts with `$U,…` ; ends `$L,…` |
| 2 | Binary Flight Data     | big-endian binary       | sequence of flight records       |
| 3 | End-of-data marker     | ASCII                   | `$E,<n>*<chksum>\r\n`            |
| 4 | Configuration XML      | XOR-0x02 obfuscated XML | between `$E` and `$V`            |
| 5 | `$V` Trailer           | ASCII                   | starts with `$V,Created by …`    |

The file may be preceded by zero-bytes or padding. Section 1 is located by
scanning for the magic two-byte sequence `0x24 0x55` (`$U`).

```
+----------------------+ 0x000000 (magic '$U')
| 1. ASCII Dollar Hdr  |
+----------------------+ end of $L,…\r\n  →  Data_Start
| 2. Binary flight data|
+----------------------+ '$E,…\r\n'
| 3. $E end marker     |
+----------------------+
| 4. Config XML (XOR2) |
+----------------------+ '$V,…\r\n'
| 5. $V trailer        |
+----------------------+ EOF
```

---

## 2. The ASCII Dollar Header (Section 1)

Each record is a CRLF-terminated line of the form:

```
$<CHAR>, field1, field2, …, fieldN*<CHKSUM-HEX>\r\n
```

The *body* of the record runs from the leading `$` up to (but not
including) the `*`. The two hex digits after `*` form the NMEA-style
XOR checksum of all body bytes.

The parser scans bytes character-by-character, building up an
`expression` until it reads `*`, then advances 5 bytes (4 for `*HH\r\n`
plus the `*` itself was already consumed by the scan).

> **NUL-tolerance.** The parser **silently skips NUL (`0x00`) bytes**
> that appear inside the ASCII section. This has been observed in
> the wild on `$T` records, where a stray `0x00` can sit between the
> seconds and milliseconds field. Implementations must filter NULs
> while building the line, not split on them.

### 2.1 Record types

| Tag  | Purpose                          | Required? | Mask bit   |
|------|----------------------------------|-----------|-----------:|
| `$U` | User / aircraft tail / serial    | yes       | 0x40       |
| `$A` | Limits configuration             | yes       | 0x01       |
| `$F` | Fuel-flow unit configuration     | yes       | 0x08       |
| `$T` | Download date/time               | yes       | 0x20       |
| `$C` | System / unit configuration      | yes       | 0x02       |
| `$P` | Protocol ID                      | optional  | —          |
| `$H` | Header flags (fuel-level bits)   | optional  | —          |
| `$E` | Empty-file marker                | optional  | —          |
| `$D` | Flight record directory entry    | yes       | 0x04       |
| `$I` | Per-sensor configuration         | optional  | —          |
| `$W` | Reserved / unknown               | optional  | —          |
| `$L` | End-of-header / data length      | yes       | 0x10       |

The seven required masks (0x01 + 0x02 + 0x04 + 0x08 + 0x10 + 0x20 +
0x40 = `0x7F` = 127) must all be set; otherwise the parser reports
"No Flight Data in Download!".

### 2.2 `$U` — Aircraft / Serial

```
$U, SN38947*75
```

* Field 1: tail number or device serial. Free-form ASCII, leading
  spaces stripped. Stored as `user_name`.

### 2.3 `$A` — Limits

```
$A, BAT, OIL, TIT, CHTH, CHTL, EGT, OILH, ?
$A, 16, 12, 500, 450, 60, -999999, 230, 100*6A
```

Indexes 1, 4, 5, 6, 7 are consumed:

| Idx | Field             | Meaning                                                 | Notes                          |
|----:|-------------------|---------------------------------------------------------|--------------------------------|
| 1   | `Bat_Limit`       | Battery alarm threshold                                 | stored as `int * 0.1` Volts    |
| 2   | (reserved)        | parsed but unused                                       |                                |
| 3   | (reserved)        | parsed but unused                                       |                                |
| 4   | `Cht_Limit`       | CHT high alarm                                          | °F or °C per `$C` flag         |
| 5   | `Cht_Low`         | CHT low alarm                                           | `-999999` ⇒ disabled           |
| 6   | `Egt_Limit`       | EGT differential alarm                                  | °F or °C                       |
| 7   | `Oil_Limit`       | Oil temperature high alarm                              |                                |
| 8   | (reserved)        | parsed but unused                                       |                                |

### 2.4 `$F` — Fuel-flow Unit

```
$F, fUnit, k1, k2, k3, k4*hh
$F,0,50,0,2990,2990*6F
```

Only field 1 (`fUnit`) is consumed. Values:

| `fUnit` | Meaning              | Effect on data scaling                          |
|--------:|----------------------|-------------------------------------------------|
|   0     | gallons (US) / G·hr  | FF / USD use scale=10 (one decimal place)       |
|  ≥ 1    | pounds, kg, liters   | FF / USD use scale=1 (integer)                  |

### 2.5 `$T` — Download date and time

```
$T, MM, DD, YY, HH, MM, SSS*hh
$T, 10, 3, 22, 10, 32, 69*…    (Oct 3, 2022 10:32:00.069)
```

Six numeric fields:

| Idx | Field      | Range  | Notes                                          |
|----:|------------|--------|------------------------------------------------|
| 1   | month      | 1-12   |                                                |
| 2   | day        | 1-31   |                                                |
| 3   | year       | 0-99   | `<75 → 20YY`, otherwise `19YY`                 |
| 4   | hour       | 0-23   |                                                |
| 5   | minute     | 0-59   |                                                |
| 6   | seconds-ms | 0-…    | `secs = N // 1000`, `ms = N % 1000`            |

### 2.6 `$C` — System Configuration

```
$C, model, Cfg_Word_packed, eng_mask, sw_extras, oat_mask, …, sw_version[, build, beta]*hh
$C,830,63741,32273,1536,16610,120,352,2,0*60
```

Field 1 is the device model code. Known values:

| Model | Class                  | Twin? |
|------:|------------------------|:-----:|
| 700   | EDM-700 (legacy)       | no    |
| 711   | EDM-711                | no    |
| 730   | EDM-730                | no    |
| 740   | EDM-740                | no    |
| 760   | EDM-760 (twin)         | yes   |
| 790   | EDM-790                | yes   |
| 800   | EDM-800                | no    |
| 830   | **EDM-830**            | no    |
| 831   | EDM-831                | no    |
| 900   | EDM-900                | no    |
| 930   | EDM-930                | no    |
| 950   | EDM-950                | no    |
| 960   | EDM-960                | yes   |

Derived flags:

* `Edm_Typ = (Model >= 900)` initial classification (newer-generation
  units use 2-byte words in data records). For EDM-830 the `$P`
  record sets `Edm_Typ = true` regardless. **EDM-830/831 may flip
  back to `Edm_Typ_actual = false` per-flight via the XOR-zero check
  described in §3.2.2.**
* `Twin_Flg` is true for models 760, 790, 960.
* `eng_deg_str` = `"F"` if `(field3 & 0x1000)` else `"C"`.
* `oat_deg_str` = `"F"` if `(field5 & 0x2000)` else `"C"`.

Field 2 (the packed `Cfg_Word`) is split into two bytes used as a
secondary search key when looking up flight records by config word.
The high byte is `Cfg_High_Byt`, the low byte `Cfg_Low_Byt`.

The last 1–3 numeric fields encode software identification:

| Number of fields | sw_version | build | beta |
|-----------------:|-----------|-------|------|
| 8 (no build/beta)| last      | "-1"  | "-1" |
| 9                | last-1    | last  | last (one extra) |
| 10 (with both)   | last-2    | last-1| last |

### 2.7 `$P` — Protocol ID

```
$P, 2*6E
```

Sets `Protocol_Id` (integer). The decoder distinguishes:

* `Protocol_Id == 2` ⇒ binary data records use **2-byte words** and
  **additive (mod-256) checksums**.
* otherwise ⇒ legacy XOR checksums.

### 2.8 `$H` — Header flags

```
$H, flags*hh
$H,0*54
```

Single integer; bits 7 and 8 form `Fvl_Bit` (fuel-level reporting
mode), exposed via `GetFuelLevelBit`.

### 2.9 `$D` — Flight directory entry

```
$D, flight_id, halfsize*hh
$D, 1224, 208*7B
```

* `flight_id`: 16-bit flight number (1-65535).
* `halfsize`: half the flight's binary size in bytes — i.e. number of
  16-bit words. The actual binary length is `halfsize * 2`.

`$D` records appear in the same order in which the flights are stored
in section 2. The number of `$D` records sets `Flt_Cnt`.

### 2.10 `$I` — Per-sensor info (EDM-930 special)

Only EDM-930 with SW version 107 / build ≥ 859 reads the optional CRB
enable bit out of a `$I` record whose first field equals `96`. EDM-830
files normally contain `$I` records but their content is ignored.

### 2.11 `$L` — Length / End of header

```
$L, n*hh
$L, 28*4A
```

Last record of the ASCII header. The byte immediately following the
trailing `\r\n` is `Data_Start`, the offset of the first byte of the
first flight record. The numeric field `n` is **not** consumed by the
parser (it advances by the fixed `cnt = 5` bytes anyway).

> **Implementer's note.** The `$U` user record carries no `, ` after
> the dollar tag in some firmware versions. The parser strips
> whitespace from individual fields before parsing.

---

## 3. The Binary Flight-Data Section (Section 2)

Section 2 starts at `Data_Start` and is the concatenation of N flight
records, where N is the number of `$D` entries. For each flight:

```
flight_record  ::= flight_header  data_record*
```

Both halves are present even when the flight is empty (the per-flight
header may also be missing in extreme edge cases — recovery code
handles 1-byte alignment slip and falls back to a
`Cfg_High_Byt`/`Cfg_Low_Byt` scan).

### 3.1 Flight-record alignment heuristics

Because each data record is a variable-length compressed record and
the firmware occasionally flushes an odd number of bytes,
neighbouring flights may be off by ±1 byte. Recovery procedure:

1. Read 2 bytes at the expected start, compare to `$D` flight_id.
2. If mismatch, retry at `start - 1`. On match, slide the start of
   *every* subsequent flight by `-1`.
3. If still no match, scan forward from `Data_Start` for the
   sequence `Cfg_High_Byt, Cfg_Low_Byt` and treat the two bytes
   *before* it as flight_id.
4. Once all flights are located, recompute each flight's actual size
   as `next.start - this.start`.

Any flight whose ID still cannot be matched is marked `found=false`
and emitted in the log as `BAD Flt#…`.

### 3.2 Flight Header

The flight header is the first record of every flight. Layout
(byte-stream, big-endian for words / longs):

| Offset (decimal)              | Size  | Field                    | Notes                                              |
|-------------------------------|------:|--------------------------|----------------------------------------------------|
| 0                             | 2     | flight_id                | matches `$D`                                       |
| 2                             | 2     | `Cfg_Word[0]`            | sensor-enable bitmap, low set                      |
| 4                             | 2     | `Cfg_Word[1]`            | sensor-enable bitmap                               |
| 6                             | 2     | `Cfg_Word[2]`            | (only if `Edm_Typ_actual`)                         |
| 8                             | 2     | `Cfg_Word[3]`            | (only if `Edm_Typ_actual`)                         |
| 10 *(or 6 in legacy form)*    | 2     | `Cfg_Word[4]`            | (only if "new header", see §3.2.1)                 |
| 12                            | 4     | `Latitude_Start`         | (only if "new header" + GPS-bearing model)         |
| 16                            | 4     | `Longitude_Start`        | (only if "new header" + GPS-bearing model)         |
| ... + 0                       | 1     | `fuelunit` (`num3`)      | mirrors `$F` value                                 |
| ... + 1                       | 1     | `horsepower` (`num4`)    | rated HP                                           |
| ... + 2                       | 2     | `Record_Interval`        | secs/sample (typ. 1 or 6)                          |
| ... + 4                       | 2     | date_word (packed)       | see §3.2.3                                         |
| ... + 6                       | 2     | time_word (packed)       | see §3.2.3                                         |
| ... + 8                       | 1     | header checksum          | makes record validate                              |

For EDM-830 with `Protocol_Id == 2`, the flight-header record has a
total length of **29 bytes** (2 + 2·5 + 4 + 4 + 1 + 1 + 2 + 2 + 2 + 1).

#### 3.2.1 "Old vs. new" header (`isNewHdr`)

EDM-830/831 (and 711/730/740) optionally carry GPS lat/lon and an
extra `Cfg_Word[4]` in their flight header. The decoder selects the
extended layout via the heuristic:

```
flag = TRUE if (binfile[Fptr+19] == binfile[Fptr+21] AND
                binfile[Fptr+20] == binfile[Fptr+22])
        OR    (binfile[Fptr+21..24] == binfile[Fptr-8..-5])
        OR    (binfile[Fptr+11] == binfile[Fptr+13])
        OR    (binfile[Fptr+12] == binfile[Fptr+14])
```

If `flag` is true *and* the model is one of `{711, 730, 740, 830,
831}`, the header includes 2 + 4 + 4 = 10 extra bytes for
`Cfg_Word[4]`, `Latitude_Start`, `Longitude_Start`.

#### 3.2.2 EDM-830 `Edm_Typ_actual` flip-back

For EDM-830/831 specifically, the decoder computes the XOR of the
first 15 header bytes; if the XOR is 0 *and* bytes Fptr+9 and Fptr+10
are equal *and* byte Fptr+11 is `0x00`, the flight header is treated
as the legacy short form (`Edm_Typ_actual = false`). Under this mode
`Cfg_Word[2..4]` are **not** read from the file (they are
zero-initialized) and subsequent data records use the 1-byte word
form (§3.3.1).

#### 3.2.3 Date / time encoding

Both fields are 16-bit big-endian words.

```
date_word = (year_2digit << 9) | (month << 5) | day
   day    =  date_word        & 0x1F
   month  = (date_word >> 5)  & 0x0F
   year2d =  date_word >> 9
   year   = year2d + (year2d < 75 ? 2000 : 1900)

time_word = (hour << 11) | (minute << 5) | (second / 2 ?)
   second_field = time_word        & 0x1F        (× 2 in firmware)
   minute       = (time_word >>5)  & 0x3F
   hour         =  time_word >> 11
```

Empirically the effective second resolution is **2 seconds**.

#### 3.2.4 Header checksum

The trailing byte makes the running checksum of the entire flight
header come out to zero. The checksum mode is selected per §3.4:

* additive mod-256 if `Protocol_Id == 2` (EDM-830 default), or any of
  the firmware-version overrides for 700/760/800.
* XOR otherwise.

### 3.3 Data records

After the flight header, the rest of the flight is a stream of
variable-length, delta-compressed data records:

```
data_record ::=  word1   word2          ; sample-mask (must equal)
                 num7                   ; multiplier / repeat count
                 ctl_byte_block         ; up to 16 control bytes
                 sgn_byte_block         ; up to 14 sign bytes (idx 6,7 skipped)
                 delta_byte_block       ; one delta byte per set bit
                 chksum                 ; 1 byte
```

#### 3.3.1 Sample mask `word1` / `word2`

* If `Edm_Typ_actual` is **true** (modern: EDM-830 default,
  EDM-9xx, etc.): `word1` and `word2` are 2-byte big-endian.
* If `Edm_Typ_actual` is **false** (legacy or EDM-830 in flip-back
  mode): both are single bytes.

The two values **must be identical**; otherwise the record is invalid
("Invalid Data Record"). Each set bit of `word1` enables one
control-byte slot in §3.3.3.

#### 3.3.2 Repeat count `num7`

A single byte read after the sample mask. Semantics:

* `num7 == 0` ⇒ this record is a brand-new sample; parse normally.
* `num7 != 0` ⇒ the *previous* record's sensor values are valid for
  `num7` additional samples. The decoder rewinds `Fptr` to the start
  of this record, decrements `Mult_Cnt`, and emits the cached row
  again. Only the first encounter actually consumes the file bytes.

This is the format's main long-run compression — long stretches of
constant readings collapse to a single record plus a counter.

#### 3.3.3 Control-byte block

For each `i` in `0..15`: if bit `i` of `word1` is 1, read **one byte**
into `Ctrl_Byte[i].ctl_byt_idx`; otherwise mark `Ctrl_Byte[i].exist =
false` and do not consume any byte.

Each control byte is itself an 8-bit bitmap that tells the decoder
which bits of the corresponding `Data_Bytes[i, *]` row are about to
receive delta updates.

#### 3.3.4 Sign-byte block

Loop `i` in `0..15`, but **skip `i==6` and `i==7`**. For each `i`
where bit `i` of `word1` is 1, read **one byte** into
`Ctrl_Byte[i].sgn_byt_idx`.

The decoder later aliases the sign-bytes for indices 6 and 7:

| Index | Aliased to                    |
|------:|-------------------------------|
| 6     | `Ctrl_Byte[0].sgn_byt_idx`    |
| 7     | `Ctrl_Byte[3].sgn_byt_idx`    |

This is because indices 6 and 7 carry the "high byte" extensions of
the EGT/RPM/etc. sensors anchored at indices 0 and 3 — they share
their sign source.

#### 3.3.5 Delta-byte block

For each `Ctrl_Byte[i]` with `exist == true`, and for each bit `j` in
`0..7`, if bit `j` of `ctl_byt_idx` is 1, read **one byte** from the
file (`num13`). This is the per-sample delta for sensor slot
`Data_Bytes[i, j]`.

The byte is multiplied by a sensor-specific gain `num11` and stored:

```
Data_Bytes[i, j].value   = num13 * num11
Data_Bytes[i, j].is_valid = (num13 != 0)
Data_Bytes[i, j].sign    = (sgn_byte_for_i[j] == 1)
```

`num11` defaults to 1, but special slots upshift by 256 (effectively
treating two control-byte slots as a 16-bit pair for a single
sensor):

| `i` | `j`        | `num11` | `num12` mod                                | Used for                 |
|----:|-----------:|--------:|--------------------------------------------|--------------------------|
| 5   | 2 or 4     | 256     | `num12 /= 2`                               | RPM high byte (L/R)      |
| 6   | any        | 256     | unchanged                                  | EGT 1-6 high byte (L)    |
| 7   | any        | 256     | unchanged                                  | EGT 1-6 high byte (R)    |
| 9   | 4 or 5     | 256     | `num12 /= 16`                              | Turbine NG/NP high       |
| 9   | 7          | 256     | unchanged                                  | engine HRS high          |
| 10  | 1 or 2     | 256     | `num12 *= 32`                              | LAT/LNG extension (turbo)|
| 12  | 4 or 5     | 256     | `num12 /= 16`                              | Right NG/NP high (twin)  |
| 12  | 7          | 256     | unchanged                                  | Right HRS high (twin)    |
| 13  | 4, 5 or 6  | 256     | `num12 /= 16`                              | EDM-960 EGT 7-9 high (L) |
| 14  | 4, 5 or 6  | 256     | `num12 /= 16`                              | EDM-960 EGT 7-9 high (R) |

The signed result `num15` for sensor decoding (§3.3.7) is:

```
num15 = +Data_Bytes[lo].value, negated if Data_Bytes[lo].sign
if hi exists:
    num15 += (-Data_Bytes[hi].value if Data_Bytes[hi].sign else +Data_Bytes[hi].value)
```

#### 3.3.6 Trailing checksum

A single byte is consumed. `calc_chksum(L)` over the entire record
(length = `Fptr_now - Fptr_start`) must produce 0.

#### 3.3.7 Per-sensor reconstruction (running totals)

Each *output* sensor is described by a `header_struct`:

```
sensor_name      // e.g. "Left EGT 1"
hdr_str          // CSV column name, e.g. "E1"
cfg_byt_idx      // index into Cfg_Word (0 or 1, occasionally 2-4)
cfg_bit_idx      // bit position; sensor is enabled iff the bit is set
scale_val        // 1.0 → integer output, 10.0 → fixed-point
m_lo_byt_idx,m_lo_bit_idx   // primary delta source in Data_Bytes
m_hi_byt_idx,m_hi_bit_idx   // optional high-byte source
running_total    // initialised to 240.0 (or 0.0 for HP and LAT/LNG)
```

For every record:

```
delta = signed value derived from m_lo (and optional m_hi) — see §3.3.5
running_total += delta
output_value   = round(running_total)            ; integer presentation
                or running_total / scale_val     ; fixed-point with one decimal
```

Special cases:

* `MARK` (`m_lo_byt_idx=2, m_lo_bit_idx=0`) is interpreted by its
  low 3 bits and bit 3:
    | val & 7 | symbol | side-effect                                 |
    |--------:|--------|---------------------------------------------|
    | 0       | (none) |                                             |
    | 1       | `X`    | pilot mark                                  |
    | 2       | `[`    | start fast-record window (Record_Interval=1)|
    | 3       | `]`    | end fast-record window (restore interval)   |
    | 4       | `<`    | alternate start fast-record                 |
    | 5       | `>`    | alternate end fast-record                   |
   Bit 3 (`val & 8`) toggles the `FuelTankNumberingFlag`.
* `DIF` / `LDIF` outputs `max(EGT) - min(EGT)` over the relevant
  EGT group within the current record.
* `RDIF` outputs the same for the right bank (twin engines only).
* `LAT` / `LNG` are formatted as `N|S` / `E|W` followed by
  `dd.mm.ss` with 6000 minutes-per-degree fixed-point:

      x = abs(running_total)
      deg  = x // 6000
      rem  = x  % 6000
      out  = "{N|S|E|W}{deg:02|03}.{rem//100:02}.{rem%100:02}"

* `HRS` (engine hours) uses a sign-reversed delta on the first
  HOB record only (`firstHOBRec`).
* Sensors whose `lo` slot is not valid in the current record fall
  back to "NA" if they also have no `hi` slot, otherwise the high
  slot's validity is checked.

#### 3.3.8 Output column header (`Col_Hdr_Str`)

The CSV-style column list is built once per flight. For every entry
in `Header[]`, the sensor is included only if its config bit is set:

```
( Cfg_Word[ cfg_byt_idx ]  AND  (1 << cfg_bit_idx) ) != 0
```

This means `Cfg_Word[0..4]` collectively form the **sensor-enable
bitmap** for the flight. Non-applicable sensors (e.g. `DIF`/`CLD` on
turbine engines) are filtered out.

### 3.4 Checksum algorithm

The same routine is used for both the flight-header and each data
record:

```
def calc_chksum(buf):
    if (Model == 760  and SW_Version >= 144) or
       (Model == 700  and SW_Version >= 296) or
       (Model == 800  and SW_Version >= 300) or
       (Edm_Typ_actual and Protocol_Id == 2):
        return sum(buf) & 0xFF                     # additive mod-256
    else:
        c = 0
        for b in buf:
            c ^= b
        return c                                   # XOR
```

**For EDM-830 with `Protocol_Id == 2` the additive variant is used**
for both the flight-header and every data record. A valid record
always sums to `0` (mod 256).

### 3.5 The `Data_Bytes[16, 8]` matrix

The decoder maintains a 16×8 matrix of delta slots. Each slot
(`byt_idx`, `bit_idx`) is a `data_byte_struct`:

```
name      // diagnostic, e.g. "CBYT5.1"
value     // most-recent delta byte (already multiplied by num11)
sign      // delta direction (additive vs subtractive)
is_valid  // false ⇒ no delta arrived this record
```

The matrix is *reset to zero* on entry to each new record. Slots that
are not refreshed by the current record stay at zero, which means "no
change" once running totals have already been applied. Sensors look
up their `(lo)` and optional `(hi)` slots in this matrix per §3.3.7.

The naming scheme `"CBYTx.y"` is purely diagnostic.

---

## 4. End-of-data Marker (`$E`)

```
$E,4*5D\r\n
```

A standalone ASCII record that immediately follows the last flight's
last data record. Parsing of the binary section stops at
`Data_Start + Σ(flight_size)` regardless, but `$E` is helpful for
file scanners. The numeric body of `$E` is the count of trailing
sections (typically `4` for a complete file: config, lat?, lng?, $V).

Implementations may locate the end of the binary section by scanning
forward for `$E,` after summing all `$D` halfsizes.

---

## 5. Configuration XML Region (Section 4)

Between the `$E,…\r\n` line and the trailing `$V,…\r\n` line lives a
region of binary data which is the unit's full XML configuration,
**XOR-encoded with the constant `0x02`**.

To recover the plaintext, XOR every byte in the region with `0x02`:

```
plain[i] = enc[i] XOR 0x02
```

After decoding, the region is a single UTF-8 XML document, framed
with `0x0D 0x0A` (CRLF) line endings — these appear in the encoded
file as `0x0F 0x08`.

A few reproducible properties confirm the encoding:

* Every occurrence of the byte pair `0x0F 0x08` inside the region
  maps to a CRLF in the decoded XML.
* The first three encoded bytes are junk (a 3-byte prefix between
  `$E,…\r\n` and the XML); the actual `<?xml` opens at offset `+3`.

Decoded structure (representative, EDM-830):

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<edm_cfg>
    <cfg_info created="…" tailno="SN…" type="exp" name="ADVISORY ONLY"/>
    <user_cal day_bl_adjust="…" night_bl_adjust="…" oat_adjust="…"
              hp_const="…" hp_value="…" hp_engine_constant="…"
              lft_map_adj="…" rht_map_adj="…" lft_amp_adj="…"
              rht_amp_adj="…" orig_tit="…" tit_adj="…"
              avg_cruise="…"/>
    <engine …/>
    <sensor …/> …
    <user_preferences oilp_display="…" oat_min_f="…" scan_rate="…"
                      egts_in_1s="…" rpm_in_1s="…" usd_remainder="…"
                      usd_to="…" tank_totalizer="…" lop_default="…"/>
    <gps_system gps_com="…"/>
    <max_lg max_lg="…"/>
    …
</edm_cfg>
```

The XML is a snapshot of the unit's settings at download time. The
cipher is trivial enough that it appears intended to deter casual
inspection rather than provide security. Implementations can usually
skip this region entirely after locating `$V`.

---

## 6. The `$V` Trailer

The very last record of the file is a single CRLF-terminated ASCII
line:

```
$V,Created by <DEVICE> VER <ver> BLD <build> BETA <beta>*<chksum>\r\n
```

Example:

```
$V,Created by EDM830 VER 3.52 BLD 002 BETA 0*57
```

The decoder finds it by scanning the **last 100 bytes** of the file
for the `$V` magic. Parsed fields:

| Token        | Stored as                  | Notes                          |
|--------------|----------------------------|--------------------------------|
| `EDM830`     | `edm_model`                | matches the device family      |
| `3.52`       | `edm_software_version`     | dotted firmware version        |
| `002`        | `edm_software_build`       | build number, zero-padded      |
| `0`          | `edm_software_is_beta`     | `1` = beta, `0` = production   |

If the build number is missing in `$C` but the `$V` string contains
`454`, the decoder retroactively sets `Build_Num = "454"`,
preserving compatibility with very old exports.

---

## 7. Sensor / `Cfg_Word` Mapping (EDM-830, single)

Each row gives the column name, which `Cfg_Word` bit enables it, and
the `Data_Bytes[lo]` (and optional `[hi]`) source.

| Sensor       | hdr_str | Cfg word [byte,bit] | lo (byte,bit) | hi (byte,bit) | Scale |
|--------------|---------|---------------------|---------------|---------------|------:|
| Left EGT 1   | E1      | (0, 2)              | (0, 0)        | (6, 0)        | 1     |
| Left EGT 2   | E2      | (0, 3)              | (0, 1)        | (6, 1)        | 1     |
| Left EGT 3   | E3      | (0, 4)              | (0, 2)        | (6, 2)        | 1     |
| Left EGT 4   | E4      | (0, 5)              | (0, 3)        | (6, 3)        | 1     |
| Left EGT 5   | E5      | (0, 6)              | (0, 4)        | (6, 4)        | 1     |
| Left EGT 6   | E6      | (0, 7)              | (0, 5)        | (6, 5)        | 1     |
| Left EGT 7   | E7      | (0, 8)              | (3, 0)        | (7, 0)        | 1     |
| Left EGT 8   | E8      | (0, 9)              | (3, 1)        | (7, 1)        | 1     |
| Left EGT 9   | E9      | (0, 10)             | (3, 2)        | (7, 2)        | 1     |
| Left CHT 1   | C1      | (0, 11)             | (1, 0)        | —             | 1     |
| Left CHT 2   | C2      | (0, 12)             | (1, 1)        | —             | 1     |
| Left CHT 3   | C3      | (0, 13)             | (1, 2)        | —             | 1     |
| Left CHT 4   | C4      | (0, 14)             | (1, 3)        | —             | 1     |
| Left CHT 5   | C5      | (0, 15)             | (1, 4)        | —             | 1     |
| Left CHT 6   | C6      | (1, 0)              | (1, 5)        | —             | 1     |
| Left CHT 7   | C7      | (1, 1)              | (3, 3)        | —             | 1     |
| Left CHT 8   | C8      | (1, 2)              | (3, 4)        | —             | 1     |
| Left CHT 9   | C9      | (1, 3)              | (3, 5)        | —             | 1     |
| Left TIT 1   | T1      | (1, 5)              | (0, 6)        | (6, 6)        | 1     |
| Left TIT 2   | T2      | (1, 6)              | (0, 7)        | (6, 7)        | 1     |
| OAT          | OAT     | (1, 9)              | (2, 5)        | —             | 1     |
| Left DIF     | DIF     | (0, 0) computed     | —             | —             | 1     |
| Left CLD     | CLD     | (0, 0) computed     | (1, 6)        | —             | 1     |
| Left CDT     | CDT     | (1, 7)              | (2, 2)        | —             | 1     |
| Left IAT     | IAT     | (1, 8)              | (2, 3)        | —             | 1     |
| Left MAP     | MAP     | (1, 14)             | (5, 0)        | —             | 10    |
| Left RPM     | RPM     | (1, 10)             | (5, 1)        | (5, 2)        | 1     |
| Left HP      | HP      | (1, 10)             | (3, 6)        | —             | 1     |
| Left FF *    | FF      | (1, 11)             | (2, 7)        | —             | 10/1  |
| Left OILP    | OILP    | (1, 13)             | (2, 1)        | —             | 1     |
| Left OILT    | OILT    | (1, 4)              | (1, 7)        | —             | 1     |
| BAT          | BAT     | (0, 0) (always)     | (2, 4)        | —             | 10    |
| Left USD *   | USD     | (1, 11)             | (2, 6)        | —             | 10/1  |
| MARK         | MARK    | (0, 0) (always)     | (2, 0)        | —             | 1     |

\* Scale of `FF` and `USD` is 10 if `fUnit == 0` (gallons), 1 otherwise.

### 7.1 Output formatting

* Unscaled (`scale_val == 1.0`): emit `running_total` rounded to int.
* Scaled by 10 (`scale_val == 10.0`): emit
  `f"{running_total/10:.1f}"`. Locale-specific decimal commas are
  rewritten to `.`.
* `MARK` and `LAT/LNG` formatted per §3.3.7.

---

## 8. End-to-end decoding pseudocode

```
def decode_jpi(path):
    data = open(path,'rb').read()

    # --- Section 1: ASCII header ---
    pos = data.find(b'$U')
    if pos < 0: raise HeaderNotFoundError

    flights = []
    while True:
        line, pos = read_dollar_line(data, pos)   # NUL-tolerant scan
        tag = line.split(b',', 1)[0]
        match tag:
            case b'$U': user = line[3:]
            case b'$A': parse_limits(line)
            case b'$F': fUnit = int(field1(line))
            case b'$T': download_dt = parse_T(line)
            case b'$C': model, sw, build, beta, … = parse_C(line)
                       Edm_Typ = (model >= 900)
                       Twin_Flg = model in (760,790,960)
            case b'$P': Protocol_Id = int(field1(line)); Edm_Typ=True
            case b'$H': Fvl_Bit = parse_H(line)
            case b'$D': flights.append((id,size := int(field2(line))*2))
            case b'$L': data_start = pos
                       break
            …

    # --- Section 2: binary flight data ---
    p = data_start
    for id, size in flights:
        end = p + size
        # -- flight header (29 bytes for EDM-830 P=2) --
        flight_id = u16_be(data, p);                       p += 2
        cfg = [u16_be(data, p+i*2) for i in range(2)];     p += 4
        if Edm_Typ_actual:                                  # see §3.2.2
            cfg += [u16_be(data, p+i*2) for i in range(2)] # words 2,3
            p += 4
            if isNewHdr(data, p, flight_size):
                cfg.append(u16_be(data, p)); p += 2
                if model in (711,730,740,830,831):
                    lat0 = s32_be(data, p); p += 4
                    lon0 = s32_be(data, p); p += 4
        fuelunit, hp = data[p], data[p+1]; p += 2
        rec_interval = u16_be(data, p); p += 2
        date_word = u16_be(data, p); p += 2
        time_word = u16_be(data, p); p += 2
        chksum    = data[p]; p += 1
        assert checksum_ok(...)

        # -- variable-length data records --
        while end - p >= 5:
            w1 = read_word_or_byte()
            w2 = read_word_or_byte(); assert w1 == w2
            mult = data[p]; p += 1
            if mult and Mult_Cnt > 0:
                emit_cached_row(); Mult_Cnt -= 1; continue
            ctl = read_ctl_block(w1)
            sgn = read_sgn_block(w1)
            deltas = read_delta_block(ctl, sgn)
            assert checksum_ok(record_buffer)
            apply_deltas(deltas)
            emit_row()

        p = end                                            # next flight

    # --- Section 3..5 ---
    e_idx = data.find(b'$E,', p)
    v_idx = data.rfind(b'$V,')
    cfg_xml = bytes(b ^ 0x02 for b in data[e_idx_end+1 : v_idx])
    parse_v(data[v_idx:])
```

---

## 9. Quick-reference field map

| Where                          | Field                 | Source                                           |
|--------------------------------|-----------------------|--------------------------------------------------|
| `$U` field 1                   | aircraft / serial     | `$U, SN…`                                        |
| `$T` fields 1-6                | download date/time    | `$T, MM, DD, YY, HH, MM, SSS`                    |
| `$C` field 1                   | EDM model code        | `830` for EDM-830                                |
| `$C` last 1-3 fields           | sw_version, build, β  | see §2.6                                         |
| `$P` field 1                   | protocol id           | `2` ⇒ 2-byte words + additive checksum          |
| `$D` fields 1, 2               | flight id, halfsize   | binary size = `halfsize * 2`                     |
| `$L`                           | end of header         | binary section starts immediately after          |
| flight hdr bytes 0-1           | flight_id (BE u16)    | matches `$D`                                     |
| flight hdr bytes 2-9 (or 2-19) | Cfg_Word[0..4]        | sensor-enable bitmap (and optional GPS)          |
| flight hdr bytes -9..-2        | fuelunit/hp/intvl/dt  | see §3.2                                         |
| flight hdr last byte           | additive checksum     | sum of record == 0 mod 256                       |
| data record header             | sample-mask + repeat  | §3.3.1, §3.3.2                                   |
| data record body               | ctl + sgn + deltas    | §3.3.3 – §3.3.5                                  |
| data record trailer            | additive checksum     | §3.4                                             |
| `$E,…\r\n`                     | end of binary data    | offset = `Data_Start + Σ(flight_size)`           |
| `$E…$V` body                   | XOR-0x02 XML config   | §5                                                |
| `$V,Created by …`              | software version line | §6                                                |

---

## 10. Worked example

Annotated 29-byte flight header (EDM-830, `Protocol_Id = 2`,
extended-header form with GPS), to illustrate the byte-by-byte
layout from §3.2:

```
04 c8                        flight_id = 1224
f8 fd                        Cfg_Word[0] = 0xF8FD
7e 11                        Cfg_Word[1] = 0x7E11
06 00                        Cfg_Word[2] = 0x0600
40 e2                        Cfg_Word[3] = 0x40E2
00 78                        Cfg_Word[4] = 0x0078       (extended hdr)
00 03 ad 04                  Latitude_Start  = +240900
ff f5 35 1c                  Longitude_Start = -707300
00                           fuelunit
6c                           HP = 108
00 06                        Record_Interval = 6 s
2d 38                        date 2022-09-24
5b f0                        time 11:31:24 (≈)
f5                           checksum (sum of all 29 bytes ≡ 0 mod 256)
```

The 29-byte sum modulo 256 checks to zero, confirming the additive
checksum mode is correct for EDM-830 + `Protocol_Id = 2`.
