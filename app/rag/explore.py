"""Try the retriever by hand: see which chunks come back for a question, and with what score.

    python -m app.rag.explore                         interactive, both embedders side by side
    python -m app.rag.explore "Can I work from Mexico?"
    python -m app.rag.explore --embedder tfidf --k 6 --full "office chair limit"
    python -m app.rag.explore --company "vacation next week"      company policies only

Interactive commands: :k 6   :full   :both / :gemini / :tfidf   :company / :external / :all   :q
Build the indexes first with:  python -m app.rag.ingest --embedder all
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from app import config
from app.rag import PolicyIndex
from app.rag.loaders import COMPANY_POLICY, EXTERNAL_REFERENCE

EMBEDDERS = ("gemini", "tfidf")


def load_indexes(names: list[str]) -> dict[str, PolicyIndex]:
    indexes = {}
    for name in names:
        try:
            indexes[name] = PolicyIndex.load(
                config.INDEX_DIR / name, api_key=config.GEMINI_API_KEY, min_score=config.MIN_SCORE
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"[{name}] not available: {exc}")
    if not indexes:
        sys.exit("No index found. Build one with:  python -m app.rag.ingest --embedder all")
    return indexes


def show(indexes: dict[str, PolicyIndex], query: str, k: int, source_type: str | None,
         full: bool) -> None:
    for name, index in indexes.items():
        print(f"\n-- {name} (weak below {index.min_score:.2f}) " + "-" * 40)
        try:
            hits = index.search(query, k=k, source_type=source_type)
        except Exception as exc:  # noqa: BLE001 - show API errors (quota, network) and keep going
            print(f"   search failed: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        if not hits:
            print("   (no results)")
        for rank, hit in enumerate(hits, start=1):
            flag = "  WEAK" if hit.weak else ""
            page = f", page {hit.page}" if hit.page else ""
            tag = " [external]" if hit.source_type == EXTERNAL_REFERENCE else ""
            print(f" {rank}. {hit.score:.3f}{flag}  {hit.doc_id} > {hit.section}{page}{tag}")
            body = hit.text if full else hit.snippet
            print(textwrap.indent(textwrap.fill(body, width=96), "      "))


def interactive(indexes: dict[str, PolicyIndex], k: int, source_type: str | None, full: bool) -> None:
    all_indexes = indexes
    print("Ask a policy question (:q to quit, :help for commands).")
    while True:
        try:
            line = input("\nquery> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith(":"):
            cmd, _, arg = line[1:].partition(" ")
            if cmd in {"q", "quit", "exit"}:
                return
            if cmd == "k" and arg.isdigit():
                k = int(arg)
            elif cmd == "full":
                full = not full
            elif cmd == "both":
                indexes = all_indexes
            elif cmd in EMBEDDERS and cmd in all_indexes:
                indexes = {cmd: all_indexes[cmd]}
            elif cmd in {"company", "external", "all"}:
                source_type = {"company": COMPANY_POLICY, "external": EXTERNAL_REFERENCE}.get(cmd)
            else:
                print(__doc__)
                continue
            print(f"k={k}  full={full}  embedders={list(indexes)}  filter={source_type or 'all'}")
            continue
        show(indexes, line, k, source_type, full)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows consoles can't print every character
    parser = argparse.ArgumentParser(description="Search the policy index by hand.")
    parser.add_argument("query", nargs="*", help="question to search; omit for interactive mode")
    parser.add_argument("--embedder", choices=[*EMBEDDERS, "both"], default="both")
    parser.add_argument("--k", type=int, default=config.VECTOR_TOP_K)
    parser.add_argument("--full", action="store_true", help="print whole chunks, not snippets")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--company", action="store_true", help="company policies only")
    group.add_argument("--external", action="store_true", help="external references only")
    args = parser.parse_args(argv)

    names = list(EMBEDDERS) if args.embedder == "both" else [args.embedder]
    indexes = load_indexes(names)
    source_type = COMPANY_POLICY if args.company else EXTERNAL_REFERENCE if args.external else None
    if args.query:
        show(indexes, " ".join(args.query), args.k, source_type, args.full)
    else:
        interactive(indexes, args.k, source_type, args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
