from __future__ import annotations

import io
import uuid

import pytest
from pypdf import PdfWriter

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


def test_pdf_with_text_and_char_cap(monkeypatch):
    from pypdf import PageObject

    monkeypatch.setattr(PageObject, "extract_text", lambda self, *a, **k: "Marie: bonjour " * 50)
    out = importer.extract("a.pdf", pdf_bytes(pages=2), **KW)
    assert out.text.startswith("Marie: bonjour") and out.media_type == "application/pdf"
    with pytest.raises(importer.ImportRefused, match="characters"):
        importer.extract("a.pdf", pdf_bytes(pages=2), **{**KW, "max_chars": 500})


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
