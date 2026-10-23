"""Policy retrieval: load -> chunk -> embed -> FAISS index -> search with citations."""

from __future__ import annotations

import sys
from pathlib import Path

from app.rag.index import Hit, IndexMismatchError, PolicyIndex

__all__ = ["Hit", "IndexMismatchError", "PolicyIndex", "open_index"]


def open_index(base_dir: Path, preferred: str, api_key: str | None = None,
               min_score: float | None = None) -> PolicyIndex:
    """Load base_dir/<preferred>, falling back to the keyless tfidf index if the preferred one
    is missing or cannot embed queries (for example, no Gemini key at runtime)."""
    try:
        return PolicyIndex.load(base_dir / preferred, api_key=api_key, min_score=min_score)
    except (FileNotFoundError, ValueError) as exc:
        if preferred == "tfidf":
            raise
        print(f"WARNING: {preferred} index unavailable ({exc}); using tfidf", file=sys.stderr)
        return PolicyIndex.load(base_dir / "tfidf", min_score=min_score)
