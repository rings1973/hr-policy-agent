"""Embedders: Gemini (dense API embeddings) and TF-IDF (keyless baseline for CI and ablation).

Every embedder returns L2-normalized float32 rows, so FAISS inner product equals cosine similarity.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str
    model: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class GeminiEmbedder:
    """gemini-embedding-001 truncated to 768 dims (Matryoshka). Truncated vectors are not unit
    length, so they are re-normalized here. Documents and queries use different task types.

    The free tier counts every *text* in a batch against a 100-per-minute quota, so batching
    saves round trips but not quota. Batches are paced to stay under texts_per_minute, and a
    429 waits for the server's retryDelay instead of a fixed backoff."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-embedding-001", dim: int = 768,
                 batch_size: int = 45, texts_per_minute: int = 90, max_attempts: int = 6,
                 timeout_s: float = 60.0):
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
        )
        self.model, self.dim = model, dim
        self.batch_size, self.max_attempts = batch_size, max_attempts
        self._seconds_per_text = 60.0 / texts_per_minute
        self._next_allowed = 0.0

    def _embed(self, texts: list[str], task_type: str) -> np.ndarray:
        config = self._types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dim)
        rows: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            for attempt in range(1, self.max_attempts + 1):
                time.sleep(max(0.0, self._next_allowed - time.monotonic()))
                try:
                    result = self._client.models.embed_content(
                        model=self.model, contents=batch, config=config
                    )
                    rows.extend(e.values for e in result.embeddings)
                    self._next_allowed = time.monotonic() + len(batch) * self._seconds_per_text
                    break
                except Exception as exc:  # SDK raises several error types; non-retryable ones are re-raised
                    if attempt == self.max_attempts or not _is_retryable(exc):
                        raise
                    delay = _retry_delay(exc) or min(2 ** attempt, 30)
                    print(f"gemini embed: {type(exc).__name__}, retrying in {delay:.0f}s "
                          f"(attempt {attempt}/{self.max_attempts})", file=sys.stderr)
                    self._next_allowed = time.monotonic() + delay
        return normalize(np.array(rows))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def _is_retryable(exc: Exception) -> bool:
    """Retry rate limits, server overload and timeouts; fail fast on auth or bad requests."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code == 429 or code >= 500
    return "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def _retry_delay(exc: Exception) -> float | None:
    """Seconds the API asked us to wait ("Please retry in 26.8s" / RetryInfo "26s"), plus 1s."""
    match = re.search(r"retry in ([\d.]+)s|'retryDelay': '(\d+)s'", str(exc))
    if not match:
        return None
    return float(match.group(1) or match.group(2)) + 1.0


_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class TfidfEmbedder:
    """Dense TF-IDF over the corpus vocabulary: sublinear tf and smoothed idf, as in the
    pre-P1 retriever. The vocabulary must be fitted (at ingest) or loaded (at query time)."""

    name = "tfidf"
    model = "tfidf-sublinear"

    def __init__(self, vocab: dict[str, int] | None = None, idf: list[float] | None = None):
        self.vocab = vocab or {}
        self.idf = np.asarray(idf or [], dtype=np.float32)

    @property
    def dim(self) -> int:
        return len(self.vocab)

    def fit(self, texts: list[str]) -> TfidfEmbedder:
        df: Counter[str] = Counter()
        for text in texts:
            df.update(set(tokenize(text)))
        terms = sorted(df)
        self.vocab = {t: i for i, t in enumerate(terms)}
        n = len(texts)
        self.idf = np.array([1 + math.log((1 + n) / (1 + df[t])) for t in terms], dtype=np.float32)
        return self

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token, count in Counter(tokenize(text)).items():
            index = self.vocab.get(token)
            if index is not None:
                vec[index] = (1 + math.log(count)) * self.idf[index]
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return normalize(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(self._vector(text))

    def save(self, out_dir: Path) -> None:
        state = {"vocab": self.vocab, "idf": [float(x) for x in self.idf]}
        (out_dir / "tfidf_state.json").write_text(json.dumps(state), encoding="utf-8")

    @classmethod
    def load(cls, index_dir: Path) -> TfidfEmbedder:
        state = json.loads((index_dir / "tfidf_state.json").read_text(encoding="utf-8"))
        return cls(state["vocab"], state["idf"])


def get_embedder(name: str, index_dir: Path | None = None, api_key: str | None = None) -> Embedder:
    """Build an embedder by name. For tfidf, index_dir loads the fitted vocabulary; without it
    the embedder is unfitted and must be fit() at ingest time."""
    if name == "gemini":
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for the gemini embedder")
        return GeminiEmbedder(api_key)
    if name == "tfidf":
        return TfidfEmbedder.load(index_dir) if index_dir else TfidfEmbedder()
    raise ValueError(f"unknown embedder {name!r} (expected 'gemini' or 'tfidf')")
