"""Run the evaluation cases against the agent and write results plus a Markdown report.

    python -m evaluation.run_eval                          # all cases, local agent, judge if key
    python -m evaluation.run_eval --cases W01,W03 --pause 0
    python -m evaluation.run_eval --mode rag_only --cases W01,W02,W03,W04,W05,W06,W07,W08
    python -m evaluation.run_eval --target https://<app>.onrender.com
    python -m evaluation.run_eval --retrieval-only         # top-k x embedder ablation, no LLM
    python -m evaluation.run_eval --rejudge evaluation/results/<file>.json   # judge later

Local runs pin REFERENCE_DATE=2026-10-22 so the date rules match the gold answers. A deployed
target uses its own clock, so date-dependent cases (W02, W05) can differ there.

Groq's free tier allows ~8k tokens per minute per model and one case costs ~8-10k tokens, so
--pause (default 30 s) spaces the LLM cases out; pre-routed cases skip the pause.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Self

import yaml

from evaluation import metrics, report

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "cases.yaml"
RESULTS_DIR = EVAL_DIR / "results"
REFERENCE_DATE = "2026-10-22"
CATEGORIES = {"single_doc", "multi_doc", "workflow", "ambiguous", "adversarial"}
STATUSES = {"ok", "clarify", "escalate", "pending_confirmation", "degraded", "error"}
REQUIRED = ("id", "category", "prompt", "gold_answer", "gold_facts", "gold_docs",
            "expected_tools", "expected_status")
RAG_TOOLS = {"search_policy_documents", "get_policy_section", "list_policy_documents"}


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]


def validate(cases: list[dict[str, Any]], tool_names: set[str] | None = None,
             doc_ids: set[str] | None = None, employee_ids: set[str] | None = None) -> list[str]:
    """Return a list of problems (empty when the case file is consistent)."""
    problems, seen = [], set()
    for c in cases:
        cid = c.get("id", "?")
        problems += [f"{cid}: missing {k}" for k in REQUIRED if k not in c]
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        if c.get("category") not in CATEGORIES:
            problems.append(f"{cid}: unknown category {c.get('category')!r}")
        problems += [f"{cid}: unknown status {s!r}" for s in c.get("expected_status", [])
                     if s not in STATUSES]
        tools = [*c.get("expected_tools", []), *c.get("optional_tools", []),
                 *c.get("forbidden_tools", [])]
        if tool_names is not None:
            problems += [f"{cid}: unknown tool {t!r}" for t in tools if t not in tool_names]
        overlap = set(c.get("expected_tools", [])) & set(c.get("forbidden_tools", []))
        if overlap:
            problems.append(f"{cid}: tools both expected and forbidden: {sorted(overlap)}")
        if doc_ids is not None:
            problems += [f"{cid}: unknown doc {d!r}" for d in c.get("gold_docs", [])
                         if d not in doc_ids]
        if employee_ids is not None and c.get("employee_id") not in (None, *employee_ids):
            problems.append(f"{cid}: unknown employee {c.get('employee_id')!r}")
    return problems


# --------------------------------------------------------------------------- retrieval ablation

def retrieval_ablation(cases: list[dict[str, Any]], embedders: list[str],
                       ks: list[int]) -> dict[str, Any]:
    """Top-k x embedder on every case with gold docs. Pure retrieval: no LLM calls, so it costs
    no rate limit and runs in CI on the keyless TF-IDF index."""
    from app import config
    from app.rag.index import PolicyIndex

    scored = [c for c in cases if c["gold_docs"]]
    out: dict[str, Any] = {"cases": len(scored), "ks": ks, "embedders": {}}
    for name in embedders:
        try:
            index = PolicyIndex.load(config.INDEX_DIR / name, api_key=config.GEMINI_API_KEY)
        except Exception as exc:  # noqa: BLE001 - report a missing index instead of failing
            out["embedders"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        rows = []
        for c in scored:
            hits = index.search(c["prompt"], k=max(ks))
            rows.append({"id": c["id"], **metrics.ranking_scores(
                [h.doc_id for h in hits], c["gold_docs"], ks)})
        mean = {key: round(sum(r[key] for r in rows) / len(rows), 3)
                for key in rows[0] if key != "id"}
        out["embedders"][name] = {"model": index.manifest["model"], "mean": mean, "per_case": rows}
        index.close()
    return out


# --------------------------------------------------------------------------- agent runs

class OnlyTools:
    """Hide all but some MCP tools from the agent (the rag_only ablation)."""

    def __init__(self, inner: Any, allowed: set[str]) -> None:
        self.inner, self.allowed = inner, allowed

    async def list_tools(self) -> list[Any]:
        return [t for t in await self.inner.list_tools() if t.name in self.allowed]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self.inner.call_tool(name, arguments)


class LocalTarget:
    """The agent in-process, with its own MCP server subprocess; a fresh session per case."""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def __aenter__(self) -> Self:
        from app.agent import HRAgent, LLMClient, MCPToolClient, SessionStore
        self.client = MCPToolClient(env={"REFERENCE_DATE": REFERENCE_DATE})
        await self.client.start()
        tools = OnlyTools(self.client, RAG_TOOLS) if self.mode == "rag_only" else self.client
        self.agent = HRAgent(LLMClient(), tools, today=date.fromisoformat(REFERENCE_DATE))
        self.sessions = SessionStore()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.aclose()

    async def ask(self, prompt: str, employee_id: str | None) -> dict[str, Any]:
        session = self.sessions.get()
        session.employee_id = employee_id
        return (await self.agent.run(prompt, session)).to_dict()


class HttpTarget:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def __aenter__(self) -> Self:
        import httpx
        self.http = httpx.AsyncClient(timeout=180)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.http.aclose()

    async def ask(self, prompt: str, employee_id: str | None) -> dict[str, Any]:
        r = await self.http.post(f"{self.base_url}/chat",
                                 json={"message": prompt, "employee_id": employee_id})
        r.raise_for_status()
        return r.json()


def build_evidence(response: dict[str, Any], chunk_text: dict[str, str]) -> str:
    """What the answer may rely on: retrieved chunk text plus non-search tool summaries."""
    parts = [f"[{cid}] {chunk_text.get(cid, '')}"
             for cid in metrics.retrieved_chunk_ids(response.get("tool_trace", []))]
    parts += [f"[{s['name']}] {s.get('result_summary', '')}"
              for s in response.get("tool_trace", [])
              if s.get("type") == "tool_call" and s.get("ok")]
    parts += [f"[citation {c.get('chunk_id')}] {c.get('snippet', '')}"
              for c in response.get("citations", []) if c.get("snippet")]
    return "\n".join(parts)


async def run_agent_cases(cases: list[dict[str, Any]], target: Any, judge: Any,
                          pause: float, chunk_lookup: Any) -> list[dict[str, Any]]:
    records = []
    for i, case in enumerate(cases):
        t0 = time.perf_counter()
        try:
            response = await target.ask(case["prompt"], case.get("employee_id"))
        except Exception as exc:  # noqa: BLE001 - one failed case must not end the run
            response = {"answer": "", "status": "error", "tool_trace": [], "citations": [],
                        "error": f"{type(exc).__name__}: {exc}"}
        response.setdefault("latency_ms", int((time.perf_counter() - t0) * 1000))
        ids = metrics.retrieved_chunk_ids(response.get("tool_trace", []))
        response["evidence"] = build_evidence(response, {cid: chunk_lookup(cid) for cid in ids})
        if judge is not None and response.get("answer"):
            try:
                response["judge"] = await judge.grade(response["answer"], response["evidence"],
                                                      case["gold_facts"])
            except Exception as exc:  # noqa: BLE001 - fall back to the lexical metrics
                response["judge"] = {"error": f"{type(exc).__name__}: {exc}"}
        record = {"id": case["id"], "category": case["category"], "prompt": case["prompt"],
                  "employee_id": case.get("employee_id"), "response": response,
                  "scores": metrics.score_case(case, response)}
        records.append(record)
        s = record["scores"]
        print(f"[{i + 1}/{len(cases)}] {case['id']:4} status={response.get('status'):22} "
              f"ok={s['status_ok']!s:5} tools_f1={s['tools']['f1']:.2f} "
              f"{response.get('provider') or '-'} {response.get('latency_ms')} ms"
              + (f"  judge error: {response['judge']['error'][:120]}"
                 if "error" in response.get("judge", {}) else ""), flush=True)
        llm_used = any(st.get("type") == "llm" for st in response.get("tool_trace", []))
        if pause and llm_used and i < len(cases) - 1:
            await asyncio.sleep(pause)
    return records


def chunk_text_lookup() -> Any:
    from app import config
    from app.rag import open_index
    try:
        index = open_index(config.INDEX_DIR, config.EMBEDDING_BACKEND, config.GEMINI_API_KEY)
    except Exception:  # noqa: BLE001 - without an index the judge sees tool summaries only
        return lambda _cid: ""
    return lambda cid: (index.get_chunk(cid) or {}).get("text", "")


def save(result: dict[str, Any], label: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}_{label}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return path


async def rejudge(path: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Judge a saved agent run again (e.g. one made with --judge off, or when the judge's daily
    quota ran out) without re-asking the agent. Rescores and resummarizes every case."""
    from evaluation.judge import Judge
    judge, run = Judge(), json.loads(path.read_text(encoding="utf-8"))
    case_by_id = {c["id"]: c for c in cases}
    for i, record in enumerate(run["cases"]):
        response, case = record["response"], case_by_id[record["id"]]
        if response.get("answer"):
            try:
                response["judge"] = await judge.grade(response["answer"],
                                                      response.get("evidence", ""),
                                                      case["gold_facts"])
            except Exception as exc:  # noqa: BLE001
                response["judge"] = {"error": f"{type(exc).__name__}: {exc}"}
        record["scores"] = metrics.score_case(case, response)
        print(f"[{i + 1}/{len(run['cases'])}] {record['id']} "
              f"grounded={record['scores']['groundedness']} "
              f"correct={record['scores']['correctness']}", flush=True)
    run["summary"] = metrics.summarize([case_by_id[r["id"]] for r in run["cases"]],
                                       [r["scores"] for r in run["cases"]])
    run["config"].update(judge=True, judge_model=judge.model, rejudged_from=path.name)
    return run


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases()
    problems = validate(cases)
    if problems:
        print("Case file problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.rejudge:
        run = await rejudge(args.rejudge, cases)
        label = args.rejudge.stem.split("_", 1)[1]  # keep the run's kind, e.g. full_local
        print(json.dumps(run["summary"]["overall"], indent=2))
        print(f"Saved {save(run, label).relative_to(EVAL_DIR.parent)}")
        report.write_report(RESULTS_DIR, EVAL_DIR / "report.md")
        return 0
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    started = datetime.now(UTC).isoformat(timespec="seconds")
    ks = [int(k) for k in args.ks.split(",")]

    if args.retrieval_only:
        result = {"kind": "retrieval", "started_at": started,
                  "ablation": retrieval_ablation(cases, args.embedders.split(","), ks)}
        for name, block in result["ablation"]["embedders"].items():
            print(f"{name:7} {block.get('mean') or block.get('error')}")
    else:
        os.environ.setdefault("REFERENCE_DATE", REFERENCE_DATE)
        judge = None
        if args.judge == "on":
            from evaluation.judge import Judge
            try:
                judge = Judge()
            except RuntimeError as exc:
                print(f"Judge off ({exc}); using lexical metrics", file=sys.stderr)
        target = LocalTarget(args.mode) if args.target == "local" else HttpTarget(args.target)
        async with target:
            records = await run_agent_cases(cases, target, judge, args.pause, chunk_text_lookup())
        case_by_id = {c["id"]: c for c in cases}
        summary = metrics.summarize([case_by_id[r["id"]] for r in records],
                                    [r["scores"] for r in records])
        providers: dict[str, int] = {}
        for r in records:
            key = r["response"].get("provider") or "none (pre-routed or failed)"
            providers[key] = providers.get(key, 0) + 1
        result = {"kind": "agent", "started_at": started,
                  "config": {"target": args.target, "mode": args.mode, "judge": bool(judge),
                             "judge_model": getattr(judge, "model", None),
                             "reference_date": REFERENCE_DATE if args.target == "local" else None,
                             "cases": len(records), "pause_s": args.pause},
                  "providers": providers, "summary": summary, "cases": records}
        print(json.dumps(summary["overall"], indent=2))

    if args.no_save:
        return 0
    target_label = "local" if args.target == "local" else "remote"
    label = "retrieval" if args.retrieval_only else f"{args.mode}_{target_label}"
    path = save(result, label)
    print(f"Saved {path.relative_to(EVAL_DIR.parent)}")
    if not args.no_report:
        report.write_report(RESULTS_DIR, EVAL_DIR / "report.md")
        print("Updated evaluation/report.md")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="local", help="'local' or a base URL of a deployed app")
    p.add_argument("--mode", choices=["full", "rag_only"], default="full")
    p.add_argument("--cases", help="comma-separated case ids (default: all)")
    p.add_argument("--pause", type=float, default=30.0, help="seconds between LLM cases")
    p.add_argument("--judge", choices=["on", "off"], default="on")
    p.add_argument("--retrieval-only", action="store_true")
    p.add_argument("--rejudge", type=Path, help="judge a saved agent result file again")
    p.add_argument("--embedders", default="gemini,tfidf")
    p.add_argument("--ks", default="2,4,8")
    p.add_argument("--no-save", action="store_true", help="print only; write no result file")
    p.add_argument("--no-report", action="store_true", help="do not regenerate report.md")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
