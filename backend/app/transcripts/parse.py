"""Speaker turns, chunks with exact offsets, and a language guess. Pure.

Offsets always index the text passed in (the stored, cleaned `document.text`):
`text[chunk.start:chunk.end] == chunk.text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHUNK_CHARS = 1200

# [00:12:03] Name (Company): text   |   Name: text   (the Markdown bold of **Name**: is cleaned
# away before parsing). A name is 1 to 4 words that start with a letter.
_WORD = r"[^\W\d_][\w'’.\-]{0,30}"
_SPEAKER = re.compile(
    rf"^[ ]*(?:\[\d{{1,2}}:\d{{2}}(?::\d{{2}})?\][ ]*)?"
    rf"(?P<name>{_WORD}(?:[ ]{_WORD}){{0,3}}?)"
    rf"(?:[ ]*\((?P<company>[^()\n]{{1,60}})\))?[ ]?:(?:[ ]+|$)"
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class Chunk:
    seq: int
    speaker: str | None
    start: int
    end: int
    text: str


def _turns(text: str) -> list[tuple[str | None, int, int]]:
    """(speaker, start, end) per turn: a line without a speaker continues the current turn."""
    speakers: list[str | None] = []
    starts: list[int | None] = []
    ends: list[int] = []
    pos = 0
    for line in text.split("\n"):
        m = _SPEAKER.match(line)
        body = line[m.end() :] if m else line
        if body.strip():
            first = pos + (m.end() if m else 0) + len(body) - len(body.lstrip())
            last = pos + len(line.rstrip())
        else:
            first = last = -1
        if m:
            speakers.append(m.group("name").strip())
            starts.append(first if first >= 0 else None)
            ends.append(last)
        elif first >= 0:
            if not speakers:
                speakers.append(None)
                starts.append(None)
                ends.append(-1)
            if starts[-1] is None:
                starts[-1] = first
            ends[-1] = last
        pos += len(line) + 1
    return [
        (sp, a, b)
        for sp, a, b in zip(speakers, starts, ends, strict=True)
        if a is not None and b > a
    ]


def _split(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Slices of at most MAX_CHUNK_CHARS, cut at sentence ends (a very long sentence is cut at
    the last space)."""
    if end - start <= MAX_CHUNK_CHARS:
        return [(start, end)]
    sentences: list[tuple[int, int]] = []
    last = start
    for m in _SENTENCE_END.finditer(text, start, end):
        sentences.append((last, m.start()))
        last = m.end()
    sentences.append((last, end))
    pieces: list[tuple[int, int]] = []
    for s, e in sentences:
        while e - s > MAX_CHUNK_CHARS:
            cut = text.rfind(" ", s + 1, s + MAX_CHUNK_CHARS)
            cut = cut if cut > s else s + MAX_CHUNK_CHARS
            pieces.append((s, cut))
            s = cut
            while s < e and text[s] == " ":
                s += 1
        if e > s:
            pieces.append((s, e))
    out: list[tuple[int, int]] = []
    cur_s, cur_e = pieces[0]
    for s, e in pieces[1:]:
        if e - cur_s <= MAX_CHUNK_CHARS:
            cur_e = e
        else:
            out.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    out.append((cur_s, cur_e))
    return out


def chunk_text(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for speaker, start, end in _turns(text):
        for s, e in _split(text, start, end):
            piece = text[s:e]
            if piece.strip():
                chunks.append(Chunk(len(chunks), speaker, s, e, piece))
    return chunks


# --- language ------------------------------------------------------------------------------------
_FR = frozenset(
    "le la les un une des du de au aux et ou mais donc car ni que qui quoi dont où ce cet cette "
    "ces mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs je tu il elle nous vous "
    "ils elles on ne pas plus est sont suis été être avoir ai as avons avez ont dans sur sous "
    "avec sans pour par chez très bien oui non merci bonjour alors aussi comme même tout tous "
    "cela ça y en".split()
)
_EN = frozenset(
    "the a an and or but so because that which who what this these those my your his her its our "
    "their i you he she it we they not no is are am was were be been being have has had do does "
    "did will would can could should in on at of to for from with without by very yes thanks "
    "hello hi also as all just if then there here about".split()
)
_BOTH = _FR & _EN
_WORDS = re.compile(r"[^\W\d_]+")


def detect_language(text: str) -> str | None:
    """fr, en or mixed, from the share of French vs English stop words; None without evidence."""
    fr = en = 0
    for w in _WORDS.findall(text.lower()):
        if w in _BOTH:
            continue
        if w in _FR:
            fr += 1
        elif w in _EN:
            en += 1
    if fr + en < 5:
        return None
    share = fr / (fr + en)
    if share >= 0.75:
        return "fr"
    if share <= 0.25:
        return "en"
    return "mixed"
