"""Turn an uploaded transcript file (PDF, Markdown or text) into clean text. Pure: no database.

The file content is sniffed, not only its extension. The original file is never kept: only the
text this module returns reaches the database.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PDF_TIME_BUDGET_S = 30.0
PDF_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
_WORKER = Path(__file__).with_name("_pdf_worker.py")
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class ImportRefused(ValueError):
    """The file is not acceptable (the message is safe to show)."""


@dataclass(frozen=True)
class Extracted:
    text: str
    media_type: str


_HEADING = re.compile(r"(?m)^([ \t]*)#{1,6}[ \t]+")
_QUOTE = re.compile(r"(?m)^([ \t]*)>[ \t]?")
_EMPHASIS = re.compile(r"(\*\*|__)")


def clean_text(text: str) -> str:
    """Sanitised text: control characters removed, line ends unified, light Markdown syntax
    (headings, quote marks, bold) dropped. The result is what is stored, and every chunk offset
    indexes it; cleaning it again changes nothing (idempotent)."""
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\t", " ").replace("\u00a0", " ")
    t = t.replace("\u2028", "\n").replace("\u2029", "\n")
    # Bidi controls, zero-width and tag characters (Cf), C0/C1 controls (Cc), surrogates and
    # private use go before any offset is computed (Trojan-source style reordering).
    t = "".join(
        ch for ch in t if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )
    t = _HEADING.sub(r"\1", t)
    t = _QUOTE.sub(r"\1", t)
    t = _EMPHASIS.sub("", t)
    return t.strip()


def sanitize_name(raw: str | None) -> str:
    """File name for display: no path, no control characters, at most 120 characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in unicodedata.normalize("NFKC", name) if c.isprintable())
    return name.strip(" .")[:120] or "upload"


def extension(file_name: str | None) -> str:
    name = (file_name or "").lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ImportRefused("only .pdf, .md, .markdown and .txt files are accepted")
    return ext


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _extract_pdf(data: bytes, *, max_pages: int, max_chars: int) -> str:
    """Extract in a child process: hard wall-clock timeout (killed on overrun), address-space
    limit where the OS honours it. Bytes go in, a JSON string comes back (nothing is unpickled)."""
    if b"%PDF-" not in data[:1024]:
        raise ImportRefused("the file is not a PDF (its content does not look like one)")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user-controlled value
            [
                sys.executable,
                "-I",
                str(_WORKER),
                str(max_pages),
                str(max_chars),
                str(PDF_MEMORY_LIMIT_BYTES),
            ],
            input=data,
            capture_output=True,
            timeout=PDF_TIME_BUDGET_S,
            env={},
            check=False,
        )
    except subprocess.TimeoutExpired:  # subprocess.run kills the child before re-raising
        raise ImportRefused("reading the PDF took too long") from None
    except OSError:
        raise ImportRefused("the PDF could not be read") from None
    try:
        out = json.loads(proc.stdout.decode("utf-8"))
        text, error = out.get("text"), out.get("error")
    except (ValueError, AttributeError):
        raise ImportRefused("the PDF could not be read (too heavy or damaged)") from None
    if isinstance(error, str):
        raise ImportRefused(error)
    if not isinstance(text, str):
        raise ImportRefused("the PDF could not be read")
    return text


def extract(
    file_name: str | None,
    data: bytes,
    *,
    max_bytes: int,
    max_pages: int,
    max_chars: int,
) -> Extracted:
    ext = extension(file_name)
    if not data:
        raise ImportRefused("the file is empty")
    if len(data) > max_bytes:
        raise ImportRefused(f"the file is larger than {max_bytes} bytes")
    if ext == ".pdf":
        raw = _extract_pdf(data, max_pages=max_pages, max_chars=max_chars)
        media = "application/pdf"
    else:
        head = data[:1024]
        magic = (b"%PDF-", b"PK\x03\x04", b"\x89PNG", b"\xd0\xcf\x11\xe0")
        if head.startswith(magic) or b"\x00" in data[:8192]:
            raise ImportRefused("the content is not text")
        raw = _decode(data)
        if len(raw) > max_chars:
            raise ImportRefused(f"the text is longer than {max_chars} characters")
        media = ALLOWED_EXTENSIONS[ext]
    text = clean_text(raw)
    if not text:
        raise ImportRefused("no text could be extracted")
    return Extracted(text=text, media_type=media)
