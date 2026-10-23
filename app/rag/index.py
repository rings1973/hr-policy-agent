"""FAISS vector index plus SQLite chunk metadata and a manifest describing how it was built.

Layout of one index directory (one per embedder):
    faiss.index      vectors, row i = chunk with rowid i
    chunks.sqlite3   chunk text and citation metadata, plus full section text
    manifest.json    embedder, dim, chunk parameters, corpus hash, weak-evidence threshold
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import faiss

from app.rag.chunker import MAX_WORDS, OVERLAP_WORDS, Chunk
from app.rag.embeddings import Embedder, TfidfEmbedder, get_embedder
from app.rag.loaders import Document, corpus_files

# Below this cosine score a hit is flagged weak. Calibrated per embedder on the real corpus
# (2026-10-23): Gemini scored relevant top hits 0.61-0.77 but nonsense and off-topic queries
# 0.50-0.59, so dense scores never approach zero; TF-IDF only reliably scores nonsense at ~0.
# The margin is thin, so this is one signal among several (guardrails, LLM "not covered" rule).
DEFAULT_MIN_SCORE = {"gemini": 0.60, "tfidf": 0.10}


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    page: int | None
    source_type: str
    source_url: str | None
    snippet: str
    text: str
    score: float
    weak: bool


class IndexMismatchError(RuntimeError):
    """The query embedder differs from the one the index was built with."""


def corpus_sha256(policy_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in corpus_files(policy_dir):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_index(
    docs: list[Document], chunks: list[Chunk], embedder: Embedder, out_dir: Path,
    policy_dir: Path, min_score: float | None = None,
) -> dict:
    texts = [c.embed_text for c in chunks]
    if isinstance(embedder, TfidfEmbedder):
        embedder.fit(texts)
    # Embed before touching out_dir, so a failed API build leaves no half-written index.
    vectors = embedder.embed_documents(texts)
    out_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(embedder, TfidfEmbedder):
        embedder.save(out_dir)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(out_dir / "faiss.index"))

    db_path = out_dir / "chunks.sqlite3"
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE, doc_id TEXT,"
            " title TEXT, section TEXT, page INTEGER, source_type TEXT, source_file TEXT,"
            " source_url TEXT, text TEXT, snippet TEXT)"
        )
        db.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(i, c.chunk_id, c.doc_id, c.title, c.section, c.page, c.source_type, c.source_file,
              c.source_url, c.text, c.snippet) for i, c in enumerate(chunks)],
        )
        db.execute(
            "CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT, format TEXT,"
            " source_type TEXT, source_file TEXT, source_url TEXT, sections INTEGER)"
        )
        db.executemany(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
            [(d.doc_id, d.title, d.format, d.source_type, d.source_file, d.source_url,
              len(d.sections)) for d in docs],
        )
        # Full, un-windowed section text so get_section returns the whole section.
        db.execute("CREATE TABLE sections (doc_id TEXT, heading TEXT, page INTEGER, text TEXT)")
        db.executemany(
            "INSERT INTO sections VALUES (?,?,?,?)",
            [(d.doc_id, s.heading, s.page, s.text) for d in docs for s in d.sections],
        )

    manifest = {
        "embedder": embedder.name,
        "model": embedder.model,
        "dim": int(vectors.shape[1]),
        "chunks": len(chunks),
        "documents": len(docs),
        "formats": sorted({d.format for d in docs}),
        "chunking": {"strategy": "heading-aware", "max_words": MAX_WORDS, "overlap_words": OVERLAP_WORDS},
        "min_score": min_score if min_score is not None else DEFAULT_MIN_SCORE[embedder.name],
        "corpus_sha256": corpus_sha256(policy_dir),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class PolicyIndex:
    def __init__(self, index_dir: Path, embedder: Embedder, manifest: dict,
                 min_score: float | None = None):
        self.index_dir, self.embedder, self.manifest = index_dir, embedder, manifest
        self.min_score = float(min_score if min_score is not None else manifest["min_score"])
        self._faiss = faiss.read_index(str(index_dir / "faiss.index"))
        self._db = sqlite3.connect(index_dir / "chunks.sqlite3", check_same_thread=False)
        self._db.row_factory = sqlite3.Row

    @classmethod
    def load(cls, index_dir: Path, embedder: Embedder | None = None,
             api_key: str | None = None, min_score: float | None = None) -> PolicyIndex:
        manifest_path = index_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"no index at {index_dir}; run: python -m app.rag.ingest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if embedder is None:
            embedder = get_embedder(manifest["embedder"], index_dir=index_dir, api_key=api_key)
        if (embedder.name, embedder.model, embedder.dim) != (
            manifest["embedder"], manifest["model"], manifest["dim"]
        ):
            # Vectors from different models live in unrelated spaces; mixing them silently
            # returns plausible-looking but meaningless neighbours.
            raise IndexMismatchError(
                f"index built with {manifest['embedder']}/{manifest['model']} ({manifest['dim']}d), "
                f"query embedder is {embedder.name}/{embedder.model} ({embedder.dim}d)"
            )
        return cls(index_dir, embedder, manifest, min_score)

    def search(self, query: str, k: int = 4, document_id: str | None = None,
               source_type: str | None = None) -> list[Hit]:
        query_vec = self.embedder.embed_query(query).reshape(1, -1)
        filtered = document_id is not None or source_type is not None
        # Over-fetch so filters still leave k results; the corpus is small enough to scan.
        fetch = self._faiss.ntotal if filtered else min(k * 4, self._faiss.ntotal)
        scores, rows = self._faiss.search(query_vec, fetch)
        hits: list[Hit] = []
        for score, row in zip(scores[0], rows[0], strict=True):
            if row < 0:
                continue
            r = self._db.execute("SELECT * FROM chunks WHERE rowid = ?", (int(row),)).fetchone()
            if document_id is not None and r["doc_id"] != document_id:
                continue
            if source_type is not None and r["source_type"] != source_type:
                continue
            hits.append(Hit(
                chunk_id=r["chunk_id"], doc_id=r["doc_id"], title=r["title"], section=r["section"],
                page=r["page"], source_type=r["source_type"], source_url=r["source_url"],
                snippet=r["snippet"], text=r["text"], score=round(float(score), 4),
                weak=float(score) < self.min_score,
            ))
            if len(hits) == k:
                break
        return hits

    def get_section(self, doc_id: str, heading: str) -> dict | None:
        row = self._db.execute(
            "SELECT s.doc_id, d.title, s.heading, s.page, s.text, d.source_type, d.source_url"
            " FROM sections s JOIN documents d USING (doc_id)"
            " WHERE s.doc_id = ? AND lower(s.heading) = lower(?) LIMIT 1",
            (doc_id, heading),
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM documents ORDER BY doc_id")]

    def get_chunk(self, chunk_id: str) -> dict | None:
        row = self._db.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self._db.close()


def hit_to_dict(hit: Hit) -> dict:
    return asdict(hit)
