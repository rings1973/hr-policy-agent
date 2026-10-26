"""The agent loop: route, let the LLM call MCP tools, then validate and shape the answer.

    agent = HRAgent(llm, mcp_client)
    result = await agent.run("Can I work from Mexico City for 6 weeks?", session)
    result = await agent.confirm(session, token, approve=True)   # the user's click, never the LLM
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from app import config
from app.agent import guardrails
from app.agent.llm import ChatModel, LLMUnavailable
from app.agent.mcp_client import MCPToolClient, ToolResult
from app.agent.prompts import FINAL_ANSWER_TOOL, system_prompt
from app.agent.session import Session
from app.agent.tool_schema import HIDDEN_PARAMS, to_openai_tools
from app.agent.trace import Trace, elapsed_ms

Status = Literal["ok", "clarify", "escalate", "pending_confirmation", "degraded", "error"]
TOOL_RESULT_CHARS = 6000
CHUNK_TEXT_CHARS = 1000  # per search hit shown to the model; chunks are ~250-400 words
FINALIZE_INSTRUCTION = (
    "Write your final reply to my question now, as a JSON object with the fields answer, "
    "policy_facts, recommendations, citations and status. Use only the tool results above; "
    "cite only chunk_id or doc_id#Section values that appear in them.")
DATA_TOOLS = {"lookup_employee_profile", "check_pto_balance", "project_pto_balance",
              "lookup_benefits_status",
              "check_policy_compliance"}


@dataclass
class AgentResult:
    answer: str
    status: Status
    session_id: str
    employee_id: str | None = None
    policy_facts: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)
    escalation_reason: str | None = None
    pending_action: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    provider: str | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_list(value: Any) -> list[str]:
    """Models sometimes send one string where the schema says array (seen from gpt-oss-20b);
    iterating that string would yield one 'fact' per character."""
    if value is None or value == "":
        return []
    items = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in items if str(v).strip()]


@dataclass
class _Turn:
    """What the tools returned during one run: citable evidence and pending actions."""
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_ok: bool = False
    pending: dict[str, Any] | None = None


class HRAgent:
    def __init__(self, llm: ChatModel, tools: MCPToolClient,
                 max_steps: int = config.AGENT_MAX_STEPS, today: date | None = None) -> None:
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self._today = today

    def today(self) -> date:
        if self._today:
            return self._today
        return date.fromisoformat(config.REFERENCE_DATE) if config.REFERENCE_DATE else date.today()

    async def run(self, message: str, session: Session) -> AgentResult:
        start = time.perf_counter()
        trace = Trace()
        session.employee_id = guardrails.resolve_employee(message, session.employee_id)
        route = guardrails.pre_route(message)
        trace.add("guardrail", "pre_route", result_summary=route)

        if route in ("emergency", "out_of_scope"):
            reply = (guardrails.EMERGENCY_REPLY if route == "emergency"
                     else guardrails.OUT_OF_SCOPE_REPLY)
            result = AgentResult(reply, "escalate", session.session_id, session.employee_id,
                                 escalation_reason=route)
            return self._finish(result, message, session, trace, start)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(self.today(), session.employee_id)},
            *session.history,
            {"role": "user", "content": message},
        ]
        if route != "normal":
            messages.insert(1, {"role": "system", "content": (
                f"Guardrail: this message was classified as {route}. Share relevant policy "
                "facts and the proper reporting or review channel, do not give legal advice, "
                "and set status to escalate.")})

        turn = _Turn()
        tool_defs = to_openai_tools(await self.tools.list_tools())
        known_tools = {t["function"]["name"] for t in tool_defs}
        tool_defs.append(FINAL_ANSWER_TOOL)
        provider = None
        final: dict[str, Any] | None = None
        try:
            for _ in range(self.max_steps - 1):  # the last step is reserved for _finalize
                t0 = time.perf_counter()
                reply = await self.llm.chat(messages, tool_defs)
                provider = f"{reply.provider}/{reply.model}"
                final_call = next((c for c in reply.tool_calls if c.name == "final_answer"), None)
                trace.add("llm", provider, ok=bool(reply.tool_calls),
                          latency_ms=elapsed_ms(t0), result_summary=(
                              "final answer" if final_call
                              else "calls " + ", ".join(c.name for c in reply.tool_calls)
                              if reply.tool_calls
                              else f"no tool call ({reply.finish_reason}, "
                                   f"{len(reply.content)} chars)") + f" [{reply.tokens} tok]")
                if final_call is not None:
                    final = guardrails.parse_final(final_call.arguments)
                    break
                if not reply.tool_calls:
                    # Prose instead of final_answer, or (gpt-oss on Groq) a final_answer call
                    # the provider dropped, leaving an empty reply: finalize without tools.
                    if reply.content.strip():
                        messages.append({"role": "assistant", "content": reply.content})
                    break
                messages.append({"role": "assistant", "content": reply.content or "",
                                 "tool_calls": [c.as_message() for c in reply.tool_calls]})
                for call in reply.tool_calls:
                    content = await self._run_tool(call.name, call.arguments, known_tools,
                                                   session, turn, trace)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            if final is None:
                final = await self._finalize(messages, trace)
        except LLMUnavailable as exc:
            trace.add("llm", "unavailable", ok=False, result_summary=str(exc)[:1500])
            result = AgentResult(
                "The language model is unavailable right now, so I can't answer reliably. "
                "Please try again shortly or contact People Operations.",
                "degraded", session.session_id, session.employee_id)
            return self._finish(result, message, session, trace, start)

        if final is None:
            result = AgentResult("I couldn't finish this request within the step limit. Please "
                                 "rephrase it or ask one question at a time.", "error",
                                 session.session_id, session.employee_id, provider=provider)
            return self._finish(result, message, session, trace, start)
        return self._finish(self._shape(final, route, turn, session, provider), message,
                            session, trace, start)

    async def _finalize(self, messages: list[dict[str, Any]], trace: Trace) -> dict[str, Any]:
        """Ask for the structured reply as schema-constrained JSON text, with no tools offered.
        Used when the model ends without a usable final_answer call or runs out of steps."""
        t0 = time.perf_counter()
        reply = await self.llm.chat(
            [*messages, {"role": "user", "content": FINALIZE_INSTRUCTION}], [],
            answer_schema=FINAL_ANSWER_TOOL["function"]["parameters"])
        trace.add("llm", f"{reply.provider}/{reply.model}", latency_ms=elapsed_ms(t0),
                  result_summary=f"final answer (finalize) [{reply.tokens} tok]")
        return guardrails.parse_final(reply.content)

    async def _run_tool(self, name: str, raw_args: str, known: set[str], session: Session,
                        turn: _Turn, trace: Trace) -> str:
        """Execute one model tool call and return the text the model will see."""
        try:
            args = json.loads(raw_args or "{}")
        except ValueError as exc:
            args, problem = None, str(exc)
        else:
            problem = None if isinstance(args, dict) else "arguments must be a JSON object"
        if problem:
            trace.add("tool_call", name, ok=False, result_summary=f"bad arguments: {problem}")
            return json.dumps({"error": f"Invalid JSON arguments: {problem}. Retry with valid "
                               "JSON."})
        # The schema hides these, but a model can still send extra keys: strip them here too.
        args = {k: v for k, v in args.items() if k not in HIDDEN_PARAMS}

        if name not in known:
            result = ToolResult(False, None, f"Unknown tool {name!r}. Available: "
                                f"{', '.join(sorted(known))}.", 0)
        elif "employee_id" in args and \
                str(args["employee_id"]).strip().upper() != session.employee_id:
            # Users may only see their own records; the model may not pick an id itself.
            result = ToolResult(False, None, (
                f"Access limited to the current employee ({session.employee_id})."
                if session.employee_id else
                "No employee id is known. Ask the user for their employee id."), 0)
        else:
            result = await self.tools.call_tool(name, args)

        step = trace.add("retrieval" if name == "search_policy_documents" else "tool_call", name,
                         ok=result.ok, latency_ms=result.latency_ms, arguments=args)
        if not result.ok:
            step.result_summary = (result.error or "")[:300]
            return json.dumps({"error": result.error})

        data = dict(result.data or {})
        step.result_summary = self._collect(name, data, turn)
        if name == "create_mock_hr_ticket" and data.get("status") == "pending_confirmation":
            turn.pending = {"kind": "ticket", "token": data["token"],
                            "preview": data["preview"], "expires_at": data.get("expires_at")}
            session.pending[data["token"]] = data["preview"]
            data["token"] = "[held by the app; the user must confirm]"
        return json.dumps(self._model_view(name, data), default=str,
                          separators=(",", ":"))[:TOOL_RESULT_CHARS]

    @staticmethod
    def _model_view(name: str, data: dict[str, Any]) -> dict[str, Any]:
        """What the LLM sees of a tool result. Search hits drop fields that duplicate `text`
        (snippet) or only matter to the UI (url, page, score); long chunks are trimmed. Full
        hits were already recorded as evidence, so citations still resolve."""
        if name != "search_policy_documents":
            return data
        hits = [{"chunk_id": r["chunk_id"], "title": r["title"], "section": r["section"],
                 **({"external": True} if r.get("source_type") == "external_reference" else {}),
                 **({"weak": True} if r.get("weak") else {}),
                 "text": r["text"] if len(r["text"]) <= CHUNK_TEXT_CHARS
                 else r["text"][:CHUNK_TEXT_CHARS].rsplit(" ", 1)[0] + " ..."}
                for r in data.get("results", [])]
        return {"results": hits, "weak_evidence": data.get("weak_evidence", False)}

    @staticmethod
    def _collect(name: str, data: dict[str, Any], turn: _Turn) -> str:
        """Record citable evidence from a tool result and return a one-line trace summary."""
        if name == "search_policy_documents":
            for r in data.get("results", []):
                turn.evidence[r["chunk_id"]] = {
                    "chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "title": r["title"],
                    "section": r["section"], "page": r["page"], "snippet": r["snippet"],
                    "score": r["score"], "weak": r["weak"]}
            ids = [r["chunk_id"] for r in data.get("results", [])]
            return f"{len(ids)} chunks{' (weak)' if data.get('weak_evidence') else ''}: " + \
                ", ".join(ids)
        if name == "get_policy_section":
            ref = f"{data['doc_id']}#{data['heading']}"
            turn.evidence[ref] = {"chunk_id": ref, "doc_id": data["doc_id"],
                                  "title": data.get("title"), "section": data["heading"],
                                  "page": data.get("page"), "snippet": data["text"][:240]}
            return ref
        if name in DATA_TOOLS:
            turn.data_ok = True
        if name == "project_pto_balance":
            ref = data.get("policy_ref", "")
            doc_id, _, section = ref.partition("#")
            turn.evidence.setdefault(ref, {"chunk_id": ref, "doc_id": doc_id, "title": doc_id,
                                           "section": section, "page": None,
                                           "snippet": data.get("summary") or data.get("detail")})
            return f"projected_available={data.get('projected_available')} on " \
                   f"{data.get('target_date')}"
        if name == "check_policy_compliance":
            for hit in data.get("rule_hits", []):
                doc_id, _, section = hit["policy_ref"].partition("#")
                turn.evidence.setdefault(hit["policy_ref"], {
                    "chunk_id": hit["policy_ref"], "doc_id": doc_id, "title": doc_id,
                    "section": section, "page": None, "snippet": hit["detail"]})
            return f"outcome={data.get('outcome')} approvals={data.get('required_approvals')}"
        if name == "create_mock_hr_ticket":
            return f"status={data.get('status')}"
        if name == "draft_hr_email":
            return f"status={data.get('status')} to={data.get('draft', {}).get('to', {}).get('id')}"
        return ", ".join(sorted(data))[:200]

    def _shape(self, final: dict[str, Any], route: str, turn: _Turn, session: Session,
               provider: str | None) -> AgentResult:
        citations, dropped = guardrails.validate_citations(_as_list(final.get("citations")),
                                                           turn.evidence)
        status = final.get("status") if final.get("status") in ("ok", "clarify", "escalate") \
            else "ok"
        reason = final.get("escalation_reason")
        if route in ("legal_advice", "sensitive_hr"):
            status, reason = "escalate", reason or route
        elif turn.pending and status == "ok":
            status = "pending_confirmation"
        answer = str(final.get("answer", "")).strip()
        facts = _as_list(final.get("policy_facts"))
        if not answer:
            answer, status = ("I couldn't produce an answer this time. Please try again or "
                              "rephrase the question."), "error"
        elif status == "ok" and not citations and not turn.data_ok:
            # No retrieved text and no record backs this answer: do not let it through.
            answer, facts = guardrails.NOT_COVERED_REPLY, []
        return AgentResult(
            answer=answer, status=status, session_id=session.session_id,
            employee_id=session.employee_id, policy_facts=facts,
            recommendations=_as_list(final.get("recommendations")),
            citations=citations, dropped_citations=dropped, escalation_reason=reason,
            pending_action=turn.pending, provider=provider)

    def _finish(self, result: AgentResult, message: str, session: Session, trace: Trace,
                start: float) -> AgentResult:
        result.tool_trace = trace.to_list()
        result.latency_ms = elapsed_ms(start)
        session.remember(message, result.answer)
        trace.write(session.session_id)
        return result

    async def confirm(self, session: Session, token: str, approve: bool) -> AgentResult:
        """Complete or cancel a proposed ticket. Called only from the user's explicit action."""
        start = time.perf_counter()
        trace = Trace()
        preview = session.pending.pop(token, None)
        if preview is None:
            return AgentResult("There is no pending action with that token (it may have been "
                               "used already).", "error", session.session_id, session.employee_id)
        if not approve:
            return AgentResult("Cancelled. No ticket was created.", "ok", session.session_id,
                               session.employee_id, latency_ms=elapsed_ms(start))
        result = await self.tools.call_tool("create_mock_hr_ticket",
                                            {**preview, "confirmation_token": token})
        trace.add("tool_call", "create_mock_hr_ticket", ok=result.ok,
                  latency_ms=result.latency_ms, arguments={**preview, "confirmation_token": "***"},
                  result_summary=(result.data or {}).get("status", "") if result.ok
                  else (result.error or ""))
        if not result.ok:
            answer, status = f"The ticket could not be created: {result.error}", "error"
        else:
            answer = (f"Mock ticket {result.data['ticket_id']} was created for "
                      f"{preview['employee_id']}. It is a demo record and was not sent anywhere.")
            status = "ok"
        out = AgentResult(answer, status, session.session_id, session.employee_id,
                          tool_trace=trace.to_list(), latency_ms=elapsed_ms(start))
        trace.write(session.session_id)
        return out
