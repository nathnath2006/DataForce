from __future__ import annotations

import io
import time
import uuid

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.transcripts import importer
from app.transcripts.names import Candidate, match_speaker
from app.transcripts.parse import chunk_text, detect_language

KW = {"max_bytes": 5_000_000, "max_pages": 5, "max_chars": 100_000}


def pdf_bytes(pages=1, encrypt=False, text_note=False):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    if encrypt:
        w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_valid_blank_has_no_text():
    with pytest.raises(importer.ImportRefused, match="no text"):
        importer.extract("a.pdf", pdf_bytes(), **KW)


def test_pdf_encrypted_pages_chars_notpdf():
    with pytest.raises(importer.ImportRefused, match="encrypted"):
        importer.extract("a.pdf", pdf_bytes(encrypt=True), **KW)
    with pytest.raises(importer.ImportRefused, match="pages"):
        importer.extract("a.pdf", pdf_bytes(pages=6), **KW)
    with pytest.raises(importer.ImportRefused, match="not a PDF"):
        importer.extract("a.pdf", b"hello", **KW)
    with pytest.raises(importer.ImportRefused, match="not text"):
        importer.extract("a.txt", pdf_bytes(), **KW)
    with pytest.raises(importer.ImportRefused, match="larger"):
        importer.extract("a.pdf", pdf_bytes(), **{**KW, "max_bytes": 10})
    with pytest.raises(importer.ImportRefused, match="accepted"):
        importer.extract("a.exe", b"x", **KW)


def text_pdf(content: bytes, pages: int = 1, compress: bool = False) -> bytes:
    """A PDF whose pages share one content stream (like the SR12 heavy-page probe)."""
    w = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    fref = w._add_object(font)
    stream = DecodedStreamObject()
    stream.set_data(content)
    if compress:
        stream = stream.flate_encode()
    sref = w._add_object(stream)
    for _ in range(pages):
        page = w.add_blank_page(612, 792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): fref})}
        )
        page[NameObject("/Contents")] = sref
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_with_text_and_char_cap():
    data = text_pdf(b"BT /F1 12 Tf 10 700 Td (Marie: bonjour) Tj ET", pages=2)
    out = importer.extract("a.pdf", data, **KW)
    assert out.text.startswith("Marie: bonjour") and out.media_type == "application/pdf"
    with pytest.raises(importer.ImportRefused, match="characters"):
        importer.extract("a.pdf", data, **{**KW, "max_chars": 20})


def test_pdf_heavy_page_refused_within_budget(monkeypatch):
    """SR12-02: 3 M text operators held a worker for 205 s; the child is killed at the budget."""
    monkeypatch.setattr(importer, "PDF_TIME_BUDGET_S", 3.0)
    heavy = text_pdf(b"BT /F1 12 Tf (a) Tj ET\n" * 3_000_000, compress=True)
    assert len(heavy) < 1_000_000
    t0 = time.monotonic()
    with pytest.raises(importer.ImportRefused):
        importer.extract("a.pdf", heavy, **{**KW, "max_pages": 300, "max_chars": 1_000_000})
    assert time.monotonic() - t0 < 10


def test_pdf_worker_failure_modes(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(importer.ImportRefused, match="too long"):
        importer.extract("a.pdf", pdf_bytes(), **KW)

    class R:
        stdout = b"not json"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    with pytest.raises(importer.ImportRefused, match="could not be read"):
        importer.extract("a.pdf", pdf_bytes(), **KW)


def test_clean_text_strips_format_and_bidi_controls():
    nasty = (
        "a\u2066b\u2067c\u2068d\u2069e\u202ef\u200eg\u200fh"
        "\u061ci\u00adj\u180ek\U000e0041l\x07m\x85n"
    )
    assert importer.clean_text(nasty) == "abcdefghijklmn"
    assert importer.clean_text("a\u2028b\tc\nd") == "a\nb c\nd"
    # Controls go BEFORE offsets: chunks index the cleaned text.
    t = importer.clean_text("Bob\u202e: salut\u2066 tout\nPaul: ok")
    assert t == "Bob: salut tout\nPaul: ok"
    assert all(t[c.start : c.end] == c.text for c in chunk_text(t))
    assert importer.clean_text(t) == t


def test_markdown_and_latin1():
    md = "# Titre\n**Marie**: bonjour *à* tous\n> Paul: ok".encode()
    out = importer.extract("a.md", md, **KW)
    assert "#" not in out.text and "**" not in out.text
    assert importer.clean_text(out.text) == out.text
    lat = "Marie: café très cher\x07".encode("latin-1")
    assert importer.extract("a.txt", lat, **KW).text == "Marie: café très cher"


def test_speaker_formats_and_offsets():
    t = (
        "[00:12:03] Marie Dupont (Acme): Bonjour. Le prix.\nsuite\n"
        "Paul: ok\n\nAnna Smith:\nligne apres\nIntro"
    )
    cs = chunk_text(t)
    assert [c.speaker for c in cs] == ["Marie Dupont", "Paul", "Anna Smith"]
    assert all(t[c.start : c.end] == c.text for c in cs)
    assert cs[0].text.endswith("suite")
    md = importer.clean_text("**Marie Dupont**: salut")
    assert chunk_text(md)[0].speaker == "Marie Dupont"
    lead = chunk_text("sans orateur\nPaul: x")
    assert lead[0].speaker is None


def test_long_turn_split_exact():
    t = "Bob: " + "Une phrase assez longue pour tester. " * 80
    t = t.strip()
    cs = chunk_text(t)
    assert len(cs) > 1 and all(len(c.text) <= 1200 for c in cs)
    assert all(t[c.start : c.end] == c.text for c in cs)
    assert all(c.text.endswith(".") for c in cs)


def test_name_matching():
    a, b, c = (uuid.uuid4() for _ in range(3))
    contacts = [Candidate(a, "Marie Dupont"), Candidate(b, "Marie Durand")]
    users = [Candidate(c, "Éric Martin")]
    assert match_speaker("dupont marie", contacts, users).id == a
    assert match_speaker("Marie", contacts, users) is None  # ambiguous
    assert match_speaker("M. Dupont", contacts, users).id == a
    # SR12-04/05: last name required; no initials-only; first name alone only if unique.
    assert match_speaker("Marie Curie", contacts, users) is None
    assert match_speaker("Jean-Pierre", [Candidate(a, "Jean Dupont")], []) is None
    assert match_speaker("Jean-Pierre Martin", [Candidate(a, "Jean Dupont")], []) is None
    assert match_speaker("P. D.", [Candidate(a, "Paul Durand")], []) is None
    assert match_speaker("I", [Candidate(a, "Isabelle Roux")], []) is None
    assert match_speaker("Durand", [Candidate(a, "Paul Durand")], []) is None
    assert match_speaker("Paul", [Candidate(a, "Paul Durand")], []).id == a
    assert match_speaker("Paul", [Candidate(a, "Paul Durand")], [Candidate(c, "Paul Roux")]) is None
    m = match_speaker("eric martin", contacts, users)
    assert m.kind == "user" and m.id == c
    assert match_speaker("Zed", contacts, users) is None


def test_language():
    fr = (
        "Bonjour, nous avons vu que le prix est trop cher pour notre budget et que ce n'est pas bon"
    )
    en = "Hello, we think that the price is too high for our budget and it is not what we need"
    assert detect_language(fr) == "fr"
    assert detect_language(en) == "en"
    assert detect_language(fr + " " + en) == "mixed"
    assert detect_language("ok") is None
