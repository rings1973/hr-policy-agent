"""Build evaluation/report.md from the newest result files, and serve the latest summary.

The report combines the newest file of each kind: the full agent run, the rag_only ablation run
and the retrieval-only (top-k x embedder) ablation. Result files are committed, so the report
and the app's /eval/latest show the numbers the write-up quotes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

METRICS = [
    ("status_accuracy", "Status accuracy"),
    ("workflow_completion", "Workflow completion"),
    ("clarify_escalate_accuracy", "Clarify / escalate accuracy"),
    ("tool_precision", "Tool precision"),
    ("tool_recall", "Tool recall"),
    ("tool_f1", "Tool F1"),
    ("forbidden_tool_rate", "Forbidden tool rate"),
    ("doc_recall", "Citation doc recall"),
    ("hallucinated_citation_rate", "Cases with a dropped (unbacked) citation"),
    ("correctness", "Answer correctness (judge)"),
    ("correctness_lexical", "Answer correctness (lexical)"),
    ("groundedness", "Groundedness (judge)"),
    ("groundedness_lexical", "Groundedness (lexical)"),
    ("action_safety", "Action safety"),
    ("latency_ms_p50", "Latency p50 (ms)"),
    ("latency_ms_p95", "Latency p95 (ms)"),
]


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["file"] = path.name
    return data


def newest(results_dir: Path, suffix: str) -> dict[str, Any] | None:
    """Newest result whose file name ends with `_<suffix>.json` (names start with a UTC stamp)."""
    files = sorted(results_dir.glob(f"*_{suffix}.json")) if results_dir.exists() else []
    return _load(files[-1]) if files else None


def latest_summary(results_dir: Path) -> dict[str, Any]:
    """Compact view for GET /eval/latest: headline numbers only, no per-case transcripts."""
    out: dict[str, Any] = {}
    for key, suffix in (("full", "full_local"), ("rag_only", "rag_only_local"),
                        ("remote", "full_remote")):
        run = newest(results_dir, suffix)
        if run:
            out[key] = {"file": run["file"], "started_at": run["started_at"],
                        "config": run["config"], "summary": run["summary"]}
    retrieval = newest(results_dir, "retrieval")
    if retrieval:
        out["retrieval"] = {"file": retrieval["file"], "started_at": retrieval["started_at"],
                            "mean": {k: v.get("mean") for k, v in
                                     retrieval["ablation"]["embedders"].items()}}
    return out or {"message": "No evaluation results yet. Run: python -m evaluation.run_eval"}


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value <= 1:
        return f"{value:.2f}"
    return str(value)


def _agent_section(run: dict[str, Any], title: str) -> list[str]:
    s = run["summary"]
    cats = list(s["by_category"])
    lines = [f"## {title}", "",
             f"`{run['file']}` · started {run['started_at']} · target `{run['config']['target']}`"
             f" · judge {run['config'].get('judge_model') or 'off'} · providers "
             + ", ".join(f"{k} ×{v}" for k, v in run.get("providers", {}).items()), "",
             "| Metric | Overall | " + " | ".join(cats) + " |",
             "|---|---|" + "---|" * len(cats)]
    for key, label in METRICS:
        row = [_fmt(s["overall"].get(key))] + [_fmt(s["by_category"][c].get(key)) for c in cats]
        lines.append(f"| {label} | " + " | ".join(row) + " |")
    lines.append(f"| n | {s['overall']['n']} | "
                 + " | ".join(str(s["by_category"][c]["n"]) for c in cats) + " |")
    lines += ["", "<details><summary>Per-case results</summary>", "",
              "| Case | Status | Expected | Tools called | Tool F1 | Correct | Grounded | ms |",
              "|---|---|---|---|---|---|---|---|"]
    for r in run["cases"]:
        sc, resp = r["scores"], r["response"]
        called = [st["name"] for st in resp.get("tool_trace", [])
                  if st.get("type") in ("tool_call", "retrieval")]
        correct = sc["correctness"] if sc["correctness"] is not None else sc["correctness_lexical"]
        grounded = sc["groundedness"] if sc["groundedness"] is not None \
            else sc["groundedness_lexical"]
        lines.append(f"| {r['id']} | {resp.get('status')} | {'✓' if sc['status_ok'] else '✗'} | "
                     f"{', '.join(called) or '-'} | {sc['tools']['f1']:.2f} | {_fmt(correct)} | "
                     f"{_fmt(grounded)} | {resp.get('latency_ms')} |")
    lines += ["", "</details>", ""]
    return lines


def _ablation_section(full: dict[str, Any] | None, rag: dict[str, Any] | None) -> list[str]:
    if not (full and rag):
        return []
    rag_ids = {r["id"] for r in rag["cases"]}
    same = [r for r in full["cases"] if r["id"] in rag_ids]
    if not same:
        return []
    from evaluation.metrics import summarize  # local import: report has no other deps
    cases = [{"category": r["category"]} for r in same]
    full_view = summarize(cases, [r["scores"] for r in same])["overall"]
    rag_view = rag["summary"]["overall"]
    lines = ["## Ablation: full tools vs RAG only", "",
             (f"Same {len(same)} cases; `rag_only` hides every MCP tool except search and "
              "section lookup, so personal records and rule checks are unavailable."), "",
             "| Metric | Full tools | RAG only |", "|---|---|---|"]
    for key in ("status_accuracy", "workflow_completion", "tool_recall", "correctness",
                "correctness_lexical", "groundedness", "latency_ms_p50"):
        label = dict(METRICS)[key]
        lines.append(f"| {label} | {_fmt(full_view.get(key))} | {_fmt(rag_view.get(key))} |")
    return [*lines, ""]


def _retrieval_section(run: dict[str, Any]) -> list[str]:
    ab = run["ablation"]
    keys = [f"{m}@{k}" for k in ab["ks"] for m in ("hit", "recall")] + ["rr"]
    lines = ["## Ablation: retrieval top-k × embedder", "",
             (f"`{run['file']}` · {ab['cases']} cases with gold documents · no LLM calls. "
              "hit@k: any gold document in the top k; recall@k: share of gold documents in the "
              "top k; rr: mean reciprocal rank of the first gold document (MRR)."), "",
             "| Embedder | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for name, block in ab["embedders"].items():
        if "mean" in block:
            lines.append(f"| {name} | " + " | ".join(_fmt(block["mean"][k]) for k in keys) + " |")
        else:
            lines.append(f"| {name} | {block['error']} |" + " |" * (len(keys) - 1))
    return [*lines, ""]


def write_report(results_dir: Path, out_path: Path) -> None:
    full = newest(results_dir, "full_local")
    rag = newest(results_dir, "rag_only_local")
    remote = newest(results_dir, "full_remote")
    retrieval = newest(results_dir, "retrieval")
    header = ["# Evaluation report", "",
              ("Generated by `python -m evaluation.run_eval` from the newest files in "
               "`evaluation/results/`. Cases and gold answers: `evaluation/cases.yaml`. Metric "
               "definitions: `evaluation/metrics.py` and `design-and-evaluation.md`."), ""]
    lines = list(header)
    if full:
        lines += _agent_section(full, "Full agent (local)")
    if remote:
        lines += _agent_section(remote, "Full agent (deployed)")
    lines += _ablation_section(full, rag)
    if retrieval:
        lines += _retrieval_section(retrieval)
    if lines == header:
        lines.append("No results yet.")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
