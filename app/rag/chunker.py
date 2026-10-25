"""Heading-aware chunking: one chunk per section, long sections split into overlapping windows."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.rag.loaders import Document

MAX_WORDS = 350
OVERLAP_WORDS = 60
SNIPPET_CHARS = 240

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
# The synthetic policies open with a one-paragraph disclaimer that lands in its own "Overview"
# section. Its title-prefixed embedding scores high (0.67 for "how many holidays?") while it holds
# no policy content, so it would take a top-k slot. Real sections never start this way.
_DISCLAIMER = re.compile(r"^\s*Synthetic policy example\b", re.IGNORECASE)
DISCLAIMER_MAX_WORDS = 60


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    page: int | None
    source_type: str
    source_file: str
    source_url: str | None
    text: str
    snippet: str

    @property
    def embed_text(self) -> str:
        """Text sent to the embedder: a contextual header plus the body, so a section called
        "Eligibility" is embedded as the eligibility rules of this particular policy."""
        return f"{self.title} > {self.section}\n\n{self.text}"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def split_sentences(text: str) -> list[str]:
    return [s for s in (p.strip() for p in _SENTENCE_END.split(text)) if s]


def window_words(text: str, max_words: int = MAX_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    """Split text into windows of at most max_words, breaking on sentence boundaries.
    Each window after the first starts with up to `overlap` words of trailing sentences
    from the previous window, so a rule straddling the boundary appears whole in one chunk."""
    if len(text.split()) <= max_words:
        return [text.strip()]
    sentences = []
    for sentence in split_sentences(text):
        words = sentence.split()
        # A single sentence longer than the window (rare; e.g. a PDF list) is hard-split.
        sentences.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))

    windows: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        if current and _count(current) + len(sentence.split()) > max_words:
            windows.append(current)
            carry: list[str] = []
            for previous in reversed(current):
                if _count(carry) + len(previous.split()) > overlap:
                    break
                carry.insert(0, previous)
            # Drop the overlap rather than let a long sentence push the window past max_words.
            current = carry if _count(carry) + len(sentence.split()) <= max_words else []
        current.append(sentence)
    if current:
        windows.append(current)
    return [" ".join(w) for w in windows]


def _count(sentences: list[str]) -> int:
    return sum(len(s.split()) for s in sentences)


def make_snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """First `limit` characters, cut back to the last sentence end (or word) inside the limit."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end >= limit // 2:
        return cut[:end + 1]
    return cut[:cut.rfind(" ")].rstrip(",;:") + "…"


def is_disclaimer_only(text: str) -> bool:
    """True for a section that is just the synthetic-policy disclaimer. The word cap keeps a
    section that starts with the disclaimer but goes on to real rules."""
    return bool(_DISCLAIMER.match(text)) and len(text.split()) <= DISCLAIMER_MAX_WORDS


def chunk_documents(
    docs: list[Document], max_words: int = MAX_WORDS, overlap: int = OVERLAP_WORDS
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        seen: Counter[str] = Counter()
        for section in doc.sections:
            if is_disclaimer_only(section.text):
                continue
            slug = slugify(section.heading)
            for text in window_words(section.text, max_words, overlap):
                # Numbering per (doc, heading) keeps ids stable and unique even when a
                # heading repeats (the OPM page has two "Non-Federal Service..." sections).
                n = seen[slug]
                seen[slug] += 1
                chunks.append(Chunk(
                    chunk_id=f"{doc.doc_id}#{slug}#{n}",
                    doc_id=doc.doc_id,
                    title=doc.title,
                    section=section.heading,
                    page=section.page,
                    source_type=doc.source_type,
                    source_file=doc.source_file,
                    source_url=doc.source_url,
                    text=text,
                    snippet=make_snippet(text),
                ))
    return chunks
