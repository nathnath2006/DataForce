"""Uploaded CSV / XLSX files: content checks (not just the extension) and parsing.

Only `.csv` and `.xlsx` are accepted: never `.xls` or macro formats. An xlsx is a zip, so it is
checked against zip bombs (entry count, total uncompressed size) before openpyxl opens it.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

import pandas as pd

from app.flows.ports import SourceError
from app.flows.sources.frame import normalize_frame

CSV_TYPE = "text/csv"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ZIP_ENTRIES = 1000
ZIP_BOMB_FACTOR = 10
MAX_COLUMNS = 500
_SNIFF_BYTES = 16 * 1024


class UploadRefused(SourceError):
    """The file is not acceptable (message safe to show)."""


@dataclass(frozen=True)
class ParsedFile:
    media_type: str
    sheet: str | None
    frame: pd.DataFrame


def sanitize_name(raw: str | None) -> str:
    """The stored name: no path, no control characters, at most 120 characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 115 - len(ext)] + dot + ext) if dot else name[:120]
    return name or "upload"


def file_kind(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    raise UploadRefused("only .csv and .xlsx files are accepted")


def check_zip(data: bytes, cap: int) -> zipfile.ZipFile:
    if not data.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(io.BytesIO(data)):
        raise UploadRefused("the file is not a valid .xlsx (its content is not an Excel workbook)")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise UploadRefused("the file is not a valid .xlsx") from None
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UploadRefused("the workbook has too many internal files")
    if sum(i.file_size for i in infos) > ZIP_BOMB_FACTOR * cap:
        raise UploadRefused("the workbook is too large once unpacked")
    names = {i.filename for i in infos}
    if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
        raise UploadRefused("the file is not an Excel workbook")
    if any("vbaproject" in n.lower() for n in names):
        raise UploadRefused("workbooks with macros are not accepted")
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        raise UploadRefused("the workbook contains unsafe paths")
    return archive


def _decode_csv(data: bytes) -> str:
    if b"\x00" in data[: _SNIFF_BYTES * 4] or data.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
        raise UploadRefused("the file is not a text CSV")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def sniff_delimiter(text: str) -> str:
    sample = text[:_SNIFF_BYTES]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample.strip() else ""
        return max(",;\t", key=first.count)


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen: dict[str, int] = {}
    names = []
    for i, raw in enumerate(df.columns, start=1):
        name = str(raw).strip()[:200]
        if not name or name.startswith("Unnamed: "):
            name = f"column_{i}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        names.append(name if count == 0 else f"{name}_{count + 1}")
    df.columns = pd.Index(names)
    return df


def _cap(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(df) > max_rows:
        df = df.iloc[:max_rows].copy()
        df.attrs["capped"] = True
    return df


def parse_file(
    name: str, data: bytes, *, cap_bytes: int, max_rows: int, sheet: str | None = None
) -> ParsedFile:
    """Parse an upload (or a stored file). Raises UploadRefused with a message fit for the user."""
    kind = file_kind(name)
    try:
        if kind == "csv":
            text = _decode_csv(data)
            if not text.strip():
                raise UploadRefused("the file is empty")
            df = pd.read_csv(
                io.StringIO(text),
                sep=sniff_delimiter(text),
                nrows=max_rows + 1,
                skip_blank_lines=True,
            )
            media, used_sheet = CSV_TYPE, None
        else:
            archive = check_zip(data, cap_bytes)
            archive.close()
            # pandas opens openpyxl with read_only=True, data_only=True, keep_links=False
            with pd.ExcelFile(io.BytesIO(data), engine="openpyxl") as book:
                names = list(book.sheet_names)
                used_sheet = sheet if sheet is not None else names[0]
                if used_sheet not in names:
                    raise UploadRefused(f"sheet {used_sheet!r} not found (sheets: {names[:20]})")
                df = book.parse(used_sheet, nrows=max_rows + 1)
            media = XLSX_TYPE
    except UploadRefused:
        raise
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError):
        raise UploadRefused("the file could not be read as a table") from None
    except Exception:  # noqa: BLE001 - parser messages may quote cell data
        raise UploadRefused("the file could not be read as a table") from None
    if df.shape[1] == 0:
        raise UploadRefused("the file has no columns")
    if df.shape[1] > MAX_COLUMNS:
        raise UploadRefused(f"the file has more than {MAX_COLUMNS} columns")
    df = normalize_frame(_cap(_clean_columns(df), max_rows))
    return ParsedFile(media, used_sheet, df)
