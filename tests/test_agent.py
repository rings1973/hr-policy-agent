"""Agent orchestrator tests: a scripted FakeLLM drives the real loop against the real hr_mcp
server (stdio subprocess, keyless TF-IDF index, pinned REFERENCE_DATE). No network, no API key.

The fake decides each step from the messages it receives, so the tests can assert exactly what
the model would have seen (no confirmation token, only allowed employee data).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import anyio
import pytest

from app.agent import (
    HRAgent,
    LLMReply,
    LLMUnavailable,
    MCPToolClient,
    Session,
    ToolCall,
    guardrails,
    trace,
)
from app.agent.llm import SKIP_SIGNATURE, with_gemini_signatures
from app.agent.tool_schema import compact_schema
from app.config import POLICY_DIR
from app.rag.chunker import chunk_documents
from app.rag.embeddings import TfidfEmbedder
from app.rag.index import build_index
from app.rag.loaders import load_documents

TODAY = date(2026, 10, 22)
Step = Callable[[list[dict[str, Any]]], LLMReply]


class FakeLLM:
    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []  # what each chat() received

    async def chat(self, messages, tools, answer_schema=None) -> LLMReply:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools,
                           "finalize": answer_schema is not None})
        if not self.steps:
            raise AssertionError("FakeLLM ran out of scripted steps")
        return self.steps.pop(0)(messages)


class DownLLM:
    async def chat(self, messages, tools, answer_schema=None) -> LLMReply:
        raise LLMUnavailable("groq/x: rate limited | gemini/y: 503")


def calls(*specs: tuple[str, dict[str, Any]]) -> Step:
    return lambda _: LLMReply("", [ToolCall(f"c{i}", name, json.dumps(args))
                                   for i, (name, args) in enumerate(specs)], "fake", "m1", 10)


def final(**fields: Any) -> Step:
    def step(messages):
        data = {"status": "ok", "citations": [], **fields}
        if callable(data["citations"]):
            data["citations"] = data["citations"](messages)
        return LLMReply("", [ToolCall("f", "final_answer", json.dumps(data))], "fake", "m1", 10)
    return step


def finalized(**fields: Any) -> Step:
    """The no-tools finalize call: the structured reply arrives as JSON content."""
    def step(messages):
        tool_reply = final(**fields)(messages)
        return LLMReply(tool_reply.tool_calls[0].arguments, [], "fake", "m1", 10)
    return step


def tool_outputs(messages) -> list[dict[str, Any]]:
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


def first_chunk_id(messages) -> str:
    return next(o for o in tool_outputs(messages) if "results" in o)["results"][0]["chunk_id"]


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    base = tmp_path_factory.mktemp("agent_index")
    docs = load_documents(POLICY_DIR)
    build_index(docs, chunk_documents(docs), TfidfEmbedder(), base / "tfidf", POLICY_DIR)
    return base


@pytest.fixture(autouse=True)
def no_trace_file(monkeypatch):
    monkeypatch.setattr(trace.Trace, "write", lambda self, session_id, path=None: None)


def run(index_dir, llm, scenario: Callable[[HRAgent], Awaitable[None]]) -> None:
    async def main() -> None:
        tools = MCPToolClient(env={"INDEX_DIR": str(index_dir), "EMBEDDING_BACKEND": "tfidf",
                                   "REFERENCE_DATE": TODAY.isoformat(), "MIN_SCORE": ""})
        await tools.start()
        try:
            await scenario(HRAgent(llm, tools, max_steps=4, today=TODAY))
        finally:
            await tools.aclose()
    anyio.run(main)


def test_eligibility_answer_keeps_only_citations_a_tool_returned(index_dir):
    llm = FakeLLM(
        calls(("search_policy_documents", {"query": "PTO notice requirements"}),
              ("check_policy_compliance", {"request_type": "pto", "employee_id": "E-1002",
                                           "days": 3, "start_date": "2026-11-09"})),
        final(answer="Yes, with manager approval.",
              citations=lambda m: [first_chunk_id(m), "made_up_policy#invented#0"]))

    async def scenario(agent):
        result = await agent.run("Can I take 3 days off from Nov 9?", Session(employee_id="E-1002"))
        assert result.status == "ok"
        assert result.answer == "Yes, with manager approval."
        assert len(result.citations) == 1 and result.citations[0]["snippet"]
        assert result.dropped_citations == ["made_up_policy#invented#0"]
        assert [s["name"] for s in result.tool_trace if s["type"] != "llm"] == [
            "pre_route", "search_policy_documents", "check_policy_compliance"]
        # The model saw slim search hits (no duplicated snippet) and the rule outcome.
        seen = tool_outputs(llm.calls[1]["messages"])
        assert "snippet" not in seen[0]["results"][0]
        assert seen[1]["outcome"] == "allowed_with_approval"
    run(index_dir, llm, scenario)


def test_ticket_is_only_proposed_and_token_never_reaches_the_model(index_dir):
    ticket = {"employee_id": "E-1002", "category": "remote_work", "subject": "Remote review",
              "summary": "Requesting review of 6 weeks in Mexico City.",
              "confirmation_token": "forged-by-model"}
    llm = FakeLLM(calls(("create_mock_hr_ticket", ticket)),
                  final(answer="I proposed a ticket for you to confirm."))

    async def scenario(agent):
        session = Session(employee_id="E-1002")
        result = await agent.run("Open a ticket for my remote work review", session)
        offered = {t["function"]["name"]: t for t in llm.calls[0]["tools"]}
        assert "confirmation_token" not in json.dumps(offered["create_mock_hr_ticket"])
        assert result.status == "pending_confirmation"
        token = result.pending_action["token"]
        assert token != "forged-by-model"           # model-supplied token was stripped
        model_view = json.dumps(llm.calls[1]["messages"])
        assert token not in model_view and "held by the app" in model_view

        done = await agent.confirm(session, token, approve=True)
        assert done.status == "ok" and "HR-0003" in done.answer
        again = await agent.confirm(session, token, approve=True)
        assert again.status == "error"              # single use
    run(index_dir, llm, scenario)


def test_cancelled_ticket_creates_nothing(index_dir):
    llm = FakeLLM(calls(("create_mock_hr_ticket", {
        "employee_id": "E-1002", "category": "other", "subject": "s", "summary": "x"})),
        final(answer="Proposed."))

    async def scenario(agent):
        session = Session(employee_id="E-1002")
        result = await agent.run("make a ticket", session)
        out = await agent.confirm(session, result.pending_action["token"], approve=False)
        assert "No ticket was created" in out.answer
        assert session.pending == {}
    run(index_dir, llm, scenario)


def test_scoping_blocks_model_chosen_employee_id(index_dir):
    llm = FakeLLM(calls(("check_pto_balance", {"employee_id": "E-1001"})),
                  final(answer="Sorry.", status="clarify"))

    async def scenario(agent):
        result = await agent.run("What is my coworker's balance?", Session(employee_id="E-1002"))
        seen = tool_outputs(llm.calls[1]["messages"])
        assert "Access limited to the current employee (E-1002)" in seen[0]["error"]
        assert "available" not in json.dumps(seen)
        assert result.tool_trace[2]["ok"] is False
    run(index_dir, llm, scenario)


def test_emergency_is_answered_without_calling_the_model(index_dir):
    llm = FakeLLM()

    async def scenario(agent):
        result = await agent.run("I'm in danger at the office", Session())
        assert result.status == "escalate" and result.answer == guardrails.EMERGENCY_REPLY
        assert llm.calls == []
    run(index_dir, llm, scenario)


def test_uncited_ok_answer_becomes_not_covered(index_dir):
    llm = FakeLLM(final(answer="Pets are welcome on Fridays."))

    async def scenario(agent):
        result = await agent.run("Can I bring my dog to work?", Session())
        assert result.answer == guardrails.NOT_COVERED_REPLY
    run(index_dir, llm, scenario)


def test_sensitive_topic_is_forced_to_escalate(index_dir):
    llm = FakeLLM(final(answer="Report it.", status="ok"))

    async def scenario(agent):
        result = await agent.run("My manager keeps harassing me", Session())
        assert result.status == "escalate" and result.escalation_reason == "sensitive_hr"
        assert "Guardrail" in llm.calls[0]["messages"][1]["content"]
    run(index_dir, llm, scenario)


def test_empty_reply_is_finalized_without_tools(index_dir):
    # gpt-oss on Groq: the final_answer call is generated but dropped, leaving an empty reply.
    empty: Step = lambda _: LLMReply("", [], "fake", "m1", 10, "stop")
    llm = FakeLLM(calls(("search_policy_documents", {"query": "remote work abroad"})), empty,
                  finalized(answer="Abroad needs review.", citations=first_chunk_id_list))

    async def scenario(agent):
        result = await agent.run("Can I work abroad?", Session())
        assert [c["finalize"] for c in llm.calls] == [False, False, True]
        assert llm.calls[-1]["tools"] == []
        assert result.status == "ok" and result.citations
        assert result.answer == "Abroad needs review."
    run(index_dir, llm, scenario)


def test_prose_reply_is_kept_as_context_for_finalize(index_dir):
    prose: Step = lambda _: LLMReply("Abroad work needs HR review.", [], "fake", "m1", 10, "stop")
    llm = FakeLLM(calls(("search_policy_documents", {"query": "remote work abroad"})), prose,
                  finalized(answer="Abroad work needs HR review.",
                            citations=first_chunk_id_list))

    async def scenario(agent):
        result = await agent.run("Can I work abroad?", Session())
        assert llm.calls[-1]["messages"][-2] == {"role": "assistant",
                                                 "content": "Abroad work needs HR review."}
        assert result.citations
    run(index_dir, llm, scenario)


def first_chunk_id_list(messages) -> list[str]:
    return [first_chunk_id(messages)]


def test_step_limit_ends_with_finalize(index_dir):
    search = calls(("search_policy_documents", {"query": "expenses"}))
    llm = FakeLLM(search, search, search,
                  finalized(answer="Done.", citations=first_chunk_id_list))

    async def scenario(agent):  # max_steps=4: three tool steps, then finalize
        result = await agent.run("What can I expense?", Session())
        assert [c["finalize"] for c in llm.calls] == [False, False, False, True]
        assert result.status == "ok"
    run(index_dir, llm, scenario)


def test_provider_outage_degrades_gracefully(index_dir):
    async def scenario(agent):
        result = await agent.run("How much PTO do I get?", Session(employee_id="E-1002"))
        assert result.status == "degraded"
        assert any(not s["ok"] and s["name"] == "unavailable" for s in result.tool_trace)
    run(index_dir, DownLLM(), scenario)


def test_compact_schema_drops_pydantic_noise_but_keeps_meaning():
    schema = {"title": "Args", "type": "object", "required": ["title"], "properties": {
        "title": {"title": "Title", "type": "string"},
        "days": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}],
                 "default": None, "title": "Days", "description": "PTO\n   days."},
        "k": {"type": "integer", "default": 4, "title": "K"}}}
    assert compact_schema(schema) == {"type": "object", "required": ["title"], "properties": {
        "title": {"type": "string"},  # a *parameter* named title survives
        "days": {"type": "number", "minimum": 0, "description": "PTO days."},
        "k": {"type": "integer", "default": 4}}}


def test_gemini_signatures_keep_own_and_fill_foreign_calls():
    own = {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"},
           "extra_content": {"google": {"thought_signature": "REAL"}}}
    foreign = ToolCall("b", "y", "{}").as_message()
    messages = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "", "tool_calls": [own, foreign]}]
    out = with_gemini_signatures(messages)
    sigs = [c["extra_content"]["google"]["thought_signature"] for c in out[1]["tool_calls"]]
    assert sigs == ["REAL", SKIP_SIGNATURE]
    assert "extra_content" not in messages[1]["tool_calls"][1]  # input not mutated


def test_projection_ref_is_citable_and_string_fields_are_not_split(index_dir):
    llm = FakeLLM(calls(("project_pto_balance", {"employee_id": "E-1002",
                                                 "target_date": "2027-12-15"})),
                  final(answer="About 19.17 days.", policy_facts="Accrual is per pay period.",
                        citations=["pto_policy#Annual PTO Entitlement"]))

    async def scenario(agent):
        result = await agent.run("By December 15th 2027 how many days will I have?",
                                 Session(employee_id="E-1002"))
        seen = tool_outputs(llm.calls[1]["messages"])[0]
        assert seen["projected_available"] == 19.17 and "carryover cap" in seen["summary"]
        assert result.policy_facts == ["Accrual is per pay period."]
        assert result.citations[0]["chunk_id"] == "pto_policy#Annual PTO Entitlement"
        assert result.dropped_citations == []
    run(index_dir, llm, scenario)
