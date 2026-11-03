"""Text normalization, safe instrument IDs and Gregorian/Jalali helpers."""
from __future__ import annotations

import re
from datetime import date, datetime
from numbers import Integral
from pathlib import Path

# --------------------------------------------------------------------------
# Persian/Arabic text normalization
# --------------------------------------------------------------------------
# TSETMC stores most names with Arabic Yeh/Kaf (ي / ك / ى); users type the
# Persian letters (ی / ک). Every text that enters the library is normalized
# to Persian letters and ASCII digits, so look-ups and joins are reliable.
_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    " ": " ",   # no-break space
    "ـ": None,  # tatweel ـ
    "‎": None, "‏": None,  # LRM / RLM marks
    "​": None, "﻿": None,  # zero-width space / BOM
})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_ZWNJ_EDGE = re.compile(r"‌+(?=\s|$)|(?<=\s)‌+|^‌+")
_ZWNJ_RUN = re.compile(r"‌{2,}")
_SPACES = re.compile(r"\s+")


def normalize(text: object) -> str:
    """Display-safe normalization: Persian ی/ک, ASCII digits, clean spaces.

    Meaningful half-spaces (ZWNJ) *inside* words are kept; ZWNJ next to a
    space or at the edges (very common in TSETMC names) is removed.
    """
    if text is None:
        return ""
    try:
        if text != text:  # NaN / pd.NA-safe check
            return ""
    except (TypeError, ValueError):
        return ""
    value = str(text).translate(_CHAR_MAP)
    value = _DIACRITICS.sub("", value)
    value = _ZWNJ_EDGE.sub("", value)
    value = _ZWNJ_RUN.sub("‌", value)
    return _SPACES.sub(" ", value).strip()


def ticker_key(text: object) -> str:
    """Matching key: normalized text without any space or half-space.

    ``ticker_key("بهین رو") == ticker_key("بهین‌رو") == ticker_key("بهينرو")``
    """
    return re.sub(r"[\s‌]+", "", normalize(text))


def normalize_or_none(text: object):
    value = normalize(text)
    return value or None


# --------------------------------------------------------------------------
# Instrument IDs (InsCode / IndexURL)
# --------------------------------------------------------------------------
# IDs are 14-19 digit numbers. A float (and Excel, which stores numbers as
# IEEE doubles) keeps only ~15-16 significant digits, so 65883838195688438
# silently becomes 65883838195688432. IDs are therefore *always* text.
_ID_RE = re.compile(r"\d{1,20}")


def coerce_id(value: object) -> str:
    """Return a safe text ID or raise ValueError with a clear explanation."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid instrument ID: {value!r}")
    if isinstance(value, float):
        raise ValueError(
            f"Instrument ID {value!r} is a float: digits may already be lost. "
            "Pass IDs as text, e.g. instrument_id='65883838195688438'.")
    if isinstance(value, Integral):
        return str(int(value))
    text = normalize(value)
    if not _ID_RE.fullmatch(text):
        raise ValueError(
            f"Invalid instrument ID {value!r}: expected digits only (as text). "
            "If the value came from Excel/CSV, read it with dtype=str.")
    return text


def is_valid_id(value: object) -> bool:
    try:
        coerce_id(value)
        return True
    except ValueError:
        return False


# Columns that hold identifiers / codes and must never become numbers.
TEXT_COLUMNS = ("IndexURL", "IRcode", "UnderlyingID", "Type", "MarketType", "Industry")


def to_excel(frame, path, *, sheet_name="Sheet1", index=True):
    """Write a DataFrame to .xlsx with ID/code columns stored as *text* cells.

    Use this (rather than CSV) when the file will be opened in Excel: Excel
    converts long digit strings in CSV files to numbers and corrupts them.
    """
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    import pandas as pd

    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = frame.reset_index() if index and frame.index.name is not None else frame
    if index and frame.index.name is None:
        data = frame.reset_index(names="index")
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    columns = list(data.columns)
    ws.append([str(c) for c in columns])
    text_cols = {i for i, c in enumerate(columns, 1) if c in TEXT_COLUMNS}
    for row in data.itertuples(index=False, name=None):
        out = []
        for i, v in enumerate(row, 1):
            if v is None or (not isinstance(v, (str, bytes)) and pd.isna(v) is True):
                out.append(None)
            elif i in text_cols:
                out.append(str(v))
            elif isinstance(v, pd.Timestamp):
                out.append(v.to_pydatetime())
            else:
                out.append(v.item() if hasattr(v, "item") else v)
        ws.append(out)
    for i in text_cols:
        letter = get_column_letter(i)
        for cell in ws[letter][1:]:
            cell.number_format = "@"
    wb.save(path)
    return path


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------
def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    """Convert Jalali (Solar Hijri) date to Gregorian date."""
    if not 1 <= jm <= 12 or not 1 <= jd <= (31 if jm <= 6 else 30):
        raise ValueError("Invalid Jalali day or month")
    jy = int(jy) + 1595
    days = -355668 + (365 * jy) + (jy // 33) * 8 + ((jy % 33) + 3) // 4
    days += jd + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        gy += 100 * ((days - 1) // 36524)
        days = (days - 1) % 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    months = [31, 29 if gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0) else 28,
              31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for month, length in enumerate(months, 1):
        if gd <= length:
            return date(gy, month, gd)
        gd -= length
    raise ValueError("Invalid Jalali date")


def gregorian_to_jalali(value: date | datetime) -> tuple[int, int, int]:
    """Convert a Gregorian date to a (year, month, day) Jalali tuple."""
    gy, gm, gd = value.year, value.month, value.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100)
            + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1])
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_str(value) -> str | None:
    """'1405/08/12' for a date/Timestamp, None for missing values."""
    if value is None:
        return None
    try:
        if value != value:  # NaT / NaN
            return None
    except (TypeError, ValueError):
        return None
    jy, jm, jd = gregorian_to_jalali(value)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def parse_persian_date(value: object) -> date:
    clean = normalize(value).replace("/", "").replace("-", "")
    if not clean.isdigit() or len(clean) not in (6, 8):
        raise ValueError(f"Unrecognized Jalali date: {value}")
    if len(clean) == 6:
        clean = "14" + clean
    return jalali_to_gregorian(int(clean[:4]), int(clean[4:6]), int(clean[6:]))


def iso_date(value: str | date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()
