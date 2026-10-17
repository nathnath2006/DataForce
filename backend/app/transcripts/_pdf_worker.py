"""Child process that extracts the text of a PDF (run as a script: `python -I _pdf_worker.py`).

Standalone on purpose: it imports nothing from `app`. It reads the PDF bytes on stdin and writes
ONE JSON object on stdout: {"text": "..."} or {"error": "safe message"}. Arguments: max_pages
max_chars memory_limit_bytes. The parent enforces the wall-clock timeout and kills this process;
the address-space limit is set here where the platform supports it.
"""

from __future__ import annotations

import io
import json
import sys
import time

_DEADLINE_S = 28.0


def _limit_memory(limit: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CPU, (35, 35))
    except (ImportError, OSError, ValueError):  # not supported here (macOS): skip
        return


def _extract(data: bytes, max_pages: int, max_chars: int) -> dict[str, str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return {"error": "encrypted PDFs are not accepted"}
        n_pages = len(reader.pages)
    except Exception:  # noqa: BLE001
        return {"error": "the file is not a readable PDF"}
    if n_pages > max_pages:
        return {"error": f"the PDF has more than {max_pages} pages"}
    deadline = time.monotonic() + _DEADLINE_S
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        if time.monotonic() > deadline:
            return {"error": "reading the PDF took too long"}
        try:
            chunk = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            return {"error": "the PDF could not be read"}
        total += len(chunk)
        if total > max_chars:
            return {"error": f"the text is longer than {max_chars} characters"}
        parts.append(chunk)
    return {"text": "\n\n".join(parts)}


def main() -> int:
    max_pages, max_chars, mem = (int(a) for a in sys.argv[1:4])
    data = sys.stdin.buffer.read()
    _limit_memory(mem)
    try:
        out = _extract(data, max_pages, max_chars)
    except MemoryError:
        out = {"error": "the PDF needs too much memory"}
    except RecursionError:
        out = {"error": "the file is not a readable PDF"}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
