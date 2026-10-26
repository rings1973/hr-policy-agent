"""Evaluation harness tests: the case file is consistent with the real tools, corpus and mock
data; the metrics compute what they claim; the runner and report work end to end with a stub
target. No LLM or network."""

from __future__ import annotations

import asyncio
import json
from collections import Counter

import pytest

from app.config import MOCK_DATA_DIR, POLICY_DIR
from app.rag.chunker import chunk_documents
from app.rag.embeddings import TfidfEmbedder
from app.rag.index import build_index
from app.rag.loaders import load_documents
from evaluation import metrics, report, run_eval
from hr_mcp.data_store import HRDataStore
from tests.test_mcp_server import EXPECTED_TOOLS

CASES = run_eval.load_cases()


def test_case_file_matches_tools_corpus_and_employees():
    docs = {d.doc_id for d in load_documents(POLICY_DIR)}
    employees = set(HRDataStore(MOCK_DATA_DIR).employee_ids())
    assert run_eval.validate(CASES, EXPECTED_TOOLS, docs, employees) == []


def test_case_mix_matches_the_plan():
    assert len(CASES) == 28
    assert Counter(c["category"] for c in CASES) == {
        "single_doc": 8, "multi_doc": 5, "workflow": 8, "ambiguous": 3, "adversarial": 4}


def test_validate_reports_problems():
    bad = [{"id": "Z1", "category": "nope", "prompt": "x", "gold_answer": "", "gold_facts": [],
            "gold_docs": ["missing_doc"], "expected_tools": ["t"], "forbidden_tools": ["t"],
            "expected_status": ["maybe"]}]
    problems = run_eval.validate(bad, {"t"}, {"pto_policy"}, set())
    assert any("category" in p for p in problems) and any("status" in p for p in problems)
    assert any("missing_doc" in p for p in problems) and any("both" in p for p in problems)


def test_tool_scores_ignore_optional_and_flag_forbidden():
    s = metrics.tool_scores(["search", "lookup", "ticket"], ["search"], ["lookup"], ["ticket"])
    assert s["recall"] == 1.0 and s["precision"] == pytest.approx(0.667, abs=1e-3)
    assert s["forbidden_used"] == 1
    assert metrics.tool_scores([], [])["f1"] == 1.0  # expected nothing, called nothing


def test_lexical_metrics():
    assert metrics.mention_coverage("Up to 5 days, expiring March 31.", ["five|5", "March 31",
                                                                         "June"]) == 0.667
    evidence = "Up to 5 unused days may be carried over; carried-over days expire on March 31."
    assert metrics.lexical_groundedness("Up to 5 unused days carry over and expire March 31.",
                                        evidence) == 1.0
    assert metrics.lexical_groundedness("Employees receive free lunch every Friday afternoon.",
                                        evidence) == 0.0


def test_action_safety_and_trace_parsing():
    trace = [{"type": "retrieval", "name": "search_policy_documents", "ok": True,
              "result_summary": "2 chunks: pto_policy#a#0, pto_policy#b#1"},
             {"type": "tool_call", "name": "create_mock_hr_ticket", "ok": True,
              "result_summary": "status=pending_confirmation"}]
    assert metrics.retrieved_chunk_ids(trace) == ["pto_policy#a#0", "pto_policy#b#1"]
    assert metrics.tools_called(trace) == ["search_policy_documents", "create_mock_hr_ticket"]
    assert metrics.action_safe(trace)
    trace[1]["result_summary"] = "status=created"
    assert not metrics.action_safe(trace)


def test_ranking_and_percentile():
    s = metrics.ranking_scores(["a", "b", "gold"], ["gold", "other"], [2, 4])
    assert s["hit@2"] == 0.0 and s["hit@4"] == 1.0 and s["recall@4"] == 0.5
    assert s["rr"] == pytest.approx(0.333, abs=1e-3)
    assert metrics.percentile([100, 200, 300, 400], 0.5) == 200
    assert metrics.percentile([], 0.5) is None


def test_retrieval_ablation_on_tfidf(tmp_path, monkeypatch):
    docs = load_documents(POLICY_DIR)
    build_index(docs, chunk_documents(docs), TfidfEmbedder(), tmp_path / "tfidf", POLICY_DIR)
    monkeypatch.setattr("app.config.INDEX_DIR", tmp_path)
    out = run_eval.retrieval_ablation(CASES, ["tfidf", "gemini"], [2, 4, 8])
    assert "error" in out["embedders"]["gemini"]  # no gemini index here: reported, not raised
    mean = out["embedders"]["tfidf"]["mean"]
    assert mean["hit@8"] >= mean["hit@4"] >= mean["hit@2"]
    assert mean["hit@4"] >= 0.7  # regression guard for the keyless baseline


class StubTarget:
    """Answers W03 correctly with a realistic trace; everything else gets an empty error."""

    async def ask(self, prompt, employee_id):
        if employee_id != "E-1002":
            return {"answer": "", "status": "error", "tool_trace": [], "citations": []}
        return {"answer": "You will have about 19.17 days by December 15, 2027.", "status": "ok",
                "provider": "stub/model", "latency_ms": 1200,
                "citations": [{"chunk_id": "pto_policy#Accrual", "doc_id": "pto_policy",
                               "snippet": "PTO accrues each pay period"}],
                "tool_trace": [{"type": "llm", "name": "stub/model", "ok": True},
                               {"type": "tool_call", "name": "project_pto_balance", "ok": True,
                                "result_summary": "projected_available=19.17 on 2027-12-15"}]}


def test_runner_scores_and_reports(tmp_path):
    cases = [c for c in CASES if c["id"] in ("W03", "S01")]
    records = asyncio.run(run_eval.run_agent_cases(cases, StubTarget(), None, 0, lambda _: ""))
    w03 = next(r for r in records if r["id"] == "W03")["scores"]
    assert w03["status_ok"] and w03["workflow_complete"] and w03["doc_recall"] == 1.0
    assert w03["correctness_lexical"] == 1.0 and w03["action_safe"]
    summary = metrics.summarize(cases, [r["scores"] for r in records])
    assert summary["overall"]["n"] == 2 and summary["by_category"]["workflow"]["n"] == 1

    run = {"kind": "agent", "started_at": "2026-10-26T00:00:00+00:00",
           "config": {"target": "local", "judge_model": None}, "providers": {"stub/model": 1},
           "summary": summary, "cases": records}
    (tmp_path / "20261026T000000Z_full_local.json").write_text(json.dumps(run), "utf-8")
    report.write_report(tmp_path, tmp_path / "report.md")
    text = (tmp_path / "report.md").read_text("utf-8")
    assert "Workflow completion" in text and "| W03 |" in text
    assert report.latest_summary(tmp_path)["full"]["summary"]["overall"]["n"] == 2
