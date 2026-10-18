"""Render docs/BUILD-REPORT.md to docs/DataForce-build-report.pdf.

Not a project dependency on purpose: run it from a throwaway venv.

    python3 -m venv /tmp/pdfenv && /tmp/pdfenv/bin/pip install markdown==3.7 xhtml2pdf==0.2.16
    /tmp/pdfenv/bin/python docs/tools/build_pdf.py

Fonts: macOS Arial (it has the ≥ → ± × glyphs the report uses). Pass --font-dir elsewhere.

xhtml2pdf quirk: a list item that has sub-items loses its bullet when its text contains inline
markup (bold, code), so write such parent items as plain text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
from pathlib import Path

import markdown
from xhtml2pdf import pisa

DOCS = Path(__file__).resolve().parents[1]
SRC = DOCS / "BUILD-REPORT.md"
OUT = DOCS / "DataForce-build-report.pdf"

CSS = """
@font-face {{ font-family: Body; src: url("{fonts}/Arial.ttf"); }}
@font-face {{ font-family: Body; src: url("{fonts}/Arial Bold.ttf"); font-weight: bold; }}
@font-face {{ font-family: Body; src: url("{fonts}/Arial Italic.ttf"); font-style: italic; }}
@font-face {{ font-family: Mono; src: url("{fonts}/Courier New.ttf"); }}
@page {{
  size: a4; margin: 2cm 1.8cm 2.2cm 1.8cm;
  @frame footer {{ -pdf-frame-content: footer; bottom: 0.9cm; left: 1.8cm; right: 1.8cm;
                   height: 0.8cm; }}
}}
body {{ font-family: Body; font-size: 9.6pt; line-height: 1.38; color: #1f2933; }}
h1 {{ font-size: 21pt; color: #0b3d63; margin: 0 0 4pt 0; -pdf-outline: true; }}
h2 {{ font-size: 14.5pt; color: #0b3d63; margin-top: 14pt; padding-bottom: 2pt;
      border-bottom: 1px solid #9fb3c8; -pdf-keep-with-next: true; }}
h3 {{ font-size: 11pt; color: #243b53; margin-top: 10pt; -pdf-keep-with-next: true; }}
p {{ margin: 3pt 0 5pt 0; }}
ul, ol {{ margin-top: 2pt; margin-bottom: 4pt; }}
li {{ margin-bottom: 1.5pt; }}
code {{ font-family: Mono; font-size: 8.6pt; color: #102a43; }}
pre {{ font-family: Mono; font-size: 7.8pt; background-color: #f0f4f8; padding: 6pt;
       border: 0.5px solid #d9e2ec; line-height: 1.25; }}
table {{ border-collapse: collapse; margin: 4pt 0 8pt 0; width: 100%; }}
th {{ background-color: #dceefb; color: #0b3d63; font-weight: bold; text-align: left;
      padding: 3pt 4pt; border: 0.5px solid #9fb3c8; font-size: 8.6pt; }}
td {{ padding: 3pt 4pt; border: 0.5px solid #bcccdc; vertical-align: top; font-size: 8.6pt; }}
blockquote {{ background-color: #fffbea; border-left: 3px solid #f0b429; padding: 4pt 8pt;
              margin: 6pt 0; color: #513c06; }}
.footer {{ font-size: 7.5pt; color: #627d98; text-align: center; }}
"""


_LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s")


_NESTED_ITEM = re.compile(r"^( +)((?:[-*]|\d+\.)\s)")


def _blank_line_before_lists(text: str) -> str:
    """Python-Markdown needs a blank line before a list that follows a paragraph (GitHub does
    not), otherwise the items are glued into the paragraph. It also needs 4 spaces per nesting
    level where GitHub accepts 2, so nested items get their indentation doubled."""
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code:
            line = _NESTED_ITEM.sub(lambda m: " " * (2 * len(m.group(1))) + m.group(2), line)
        prev = out[-1] if out else ""
        if (
            not in_code
            and _LIST_ITEM.match(line)
            and prev.strip()
            and not _LIST_ITEM.match(prev)
            and not prev.startswith((" ", "|"))
        ):
            out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


def build(font_dir: str) -> Path:
    body = markdown.markdown(
        _blank_line_before_lists(SRC.read_text(encoding="utf-8")),
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html",
    )
    # A literal "<pdf:nextpage />" line in the Markdown (kept by the md parser as raw HTML)
    # forces a page break.
    footer = (
        '<div id="footer" class="footer">DataForce · build report (M1, M1b, M2a, M2b) · generated '
        f"{dt.date.today().isoformat()} · page <pdf:pagenumber /> / <pdf:pagecount /></div>"
    )
    doc = (
        '<html><head><meta charset="utf-8"><title>'
        + html.escape("DataForce — build report (M1, M1b, M2a, M2b)")
        + "</title><style>"
        + CSS.format(fonts=font_dir)
        + "</style></head><body>"
        + footer
        + body
        + "</body></html>"
    )
    with OUT.open("wb") as fh:
        result = pisa.CreatePDF(doc, dest=fh, encoding="utf-8")
    if result.err:
        raise SystemExit(f"PDF generation failed ({result.err} errors)")
    return OUT


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-dir", default="/System/Library/Fonts/Supplemental")
    print(build(ap.parse_args().font_dir))
