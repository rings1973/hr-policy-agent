"""Build the policy index.

    python -m app.rag.ingest [--embedder gemini|tfidf|all] [--out BASE_DIR]

Writes BASE_DIR/<embedder>/. If Gemini is requested but has no key or fails (quota, outage),
the TF-IDF index is built instead so a deploy never ends up without a usable index.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from app import config
from app.rag.chunker import chunk_documents
from app.rag.embeddings import get_embedder
from app.rag.index import build_index
from app.rag.loaders import load_documents


def ingest(embedder_name: str, base_dir: Path, policy_dir: Path = config.POLICY_DIR) -> dict:
    docs = load_documents(policy_dir)
    chunks = chunk_documents(docs)
    embedder = get_embedder(embedder_name, api_key=config.GEMINI_API_KEY)
    return build_index(docs, chunks, embedder, base_dir / embedder_name, policy_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedder", choices=["gemini", "tfidf", "all"], default=config.EMBEDDING_BACKEND)
    parser.add_argument("--out", type=Path, default=config.INDEX_DIR)
    args = parser.parse_args(argv)

    names = ["gemini", "tfidf"] if args.embedder == "all" else [args.embedder]
    if "gemini" in names and not config.GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not set; building tfidf instead of gemini", file=sys.stderr)
        names = ["tfidf"]

    built = []
    for name in names:
        try:
            manifest = ingest(name, args.out)
        except Exception as exc:  # noqa: BLE001 - any embedding failure falls back to tfidf
            print(f"WARNING: {name} index failed ({type(exc).__name__}: {exc})", file=sys.stderr)
            if name != "tfidf" and "tfidf" not in names:
                names.append("tfidf")
            continue
        built.append(name)
        print(f"[{name}] {manifest['chunks']} chunks from {manifest['documents']} documents, "
              f"formats {manifest['formats']}, dim {manifest['dim']} -> {args.out / name}")

    if built:
        docs = load_documents(config.POLICY_DIR)
        per_doc = Counter(c.doc_id for c in chunk_documents(docs))
        for doc in docs:
            print(f"  {doc.doc_id:45} {doc.format:4} {doc.source_type:18} {per_doc[doc.doc_id]:3} chunks")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
