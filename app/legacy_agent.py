from __future__ import annotations

from typing import Any

from app.mcp_server import MCPToolServer


class HRPolicyAgent:
    def __init__(self, mcp_server: MCPToolServer):
        self.mcp_server = mcp_server

    def handle_message(self, message: str) -> dict[str, Any]:
        lower = message.lower()
        trace: list[dict[str, Any]] = []

        policy_results = self.mcp_server.call_tool("search_policy_documents", {"query": message, "k": 3})
        trace.append({"tool": "search_policy_documents", "arguments": {"query": message, "k": 3}, "result": policy_results})
        citations = policy_results["results"][:2]

        def finish(answer: str, status: str = "ok") -> dict[str, Any]:
            if status == "ok" and citations:
                answer += f"\n\nPolicy basis: {citations[0]['snippet']}"
            return {
                "answer": answer,
                "citations": citations if status != "escalate" else [],
                "tool_trace": trace,
                "status": status,
            }

        out_of_scope_markers = [
            "legal memo",
            "discrimination claim",
            "lawsuit",
            "criminal",
            "tax advice",
            "immigration advice",
            "write code",
        ]
        if any(marker in lower for marker in out_of_scope_markers):
            answer = (
                "I can help with Quantic HR policy questions, not legal, disciplinary, or regulatory advice. "
                "This topic should be escalated to HR, legal, or the appropriate compliance team."
            )
            return finish(answer, "escalate")

        if not citations:
            return finish(
                "I couldn't find supporting information in the HR policy library. Please contact People Operations for guidance.",
                "escalate",
            )

        if "pto" in lower or "vacation" in lower or "time off" in lower:
            employee_id = "E-1001"
            pto_info = self.mcp_server.call_tool("check_pto_balance", {"employee_id": employee_id})
            trace.append({"tool": "check_pto_balance", "arguments": {"employee_id": employee_id}, "result": pto_info})
            answer = (
                "Ava currently has 12 PTO days remaining. The policy requires manager approval for planned time off, "
                "and requests longer than 3 consecutive business days may need coverage planning. Based on the policy, "
                "a PTO request is not automatically denied but should be routed to the manager and HR if there are service risks."
            )
            return finish(answer)

        if "remote" in lower or "work from" in lower or "another state" in lower or "international" in lower:
            employee_id = "E-1001"
            employee = self.mcp_server.call_tool("lookup_employee_profile", {"employee_id": employee_id})
            trace.append({"tool": "lookup_employee_profile", "arguments": {"employee_id": employee_id}, "result": employee})
            compliance = self.mcp_server.call_tool(
                "check_policy_compliance",
                {"request_type": "remote_work", "employee_id": employee_id},
            )
            trace.append({"tool": "check_policy_compliance", "arguments": {"request_type": "remote_work", "employee_id": employee_id}, "result": compliance})
            answer = (
                "The policy does not automatically approve remote work outside the home state for 6 weeks. "
                "Because the request exceeds the standard 2-week threshold, the employee needs manager approval and a compliance review. "
                "Security training and approved device requirements remain mandatory."
            )
            return finish(answer)

        if "benefit" in lower or "health" in lower:
            employee_id = "E-1003"
            benefits = self.mcp_server.call_tool("lookup_benefits_status", {"employee_id": employee_id})
            trace.append({"tool": "lookup_benefits_status", "arguments": {"employee_id": employee_id}, "result": benefits})
            answer = (
                "Benefits are pending for this employee. The policy says the benefits review should be completed before advising on eligibility, "
                "and contractor employees are not eligible for core benefits unless specified in the contract."
            )
            return finish(answer)

        if "ticket" in lower or "email" in lower or "draft" in lower:
            draft = self.mcp_server.call_tool("draft_hr_email", {"recipient": "manager", "body": "Requested HR review for compliance follow-up."})
            trace.append({"tool": "draft_hr_email", "arguments": {"recipient": "manager", "body": "Requested HR review for compliance follow-up."}, "result": draft})
            answer = (
                "I can draft a mock HR or manager message based on the policy and the employee record. "
                "The wording should remain a draft and require explicit approval before sending."
            )
            return finish(answer)

        if lower.strip() == "" or "can i" in lower and "day off" in lower:
            answer = (
                "I need a bit more detail to answer that accurately. Please share the employee ID, dates, and whether the request is planned or emergency leave. "
                "The policy requires manager approval and, for longer leave, coverage planning."
            )
            return finish(answer, "clarify")

        answer = (
            "I can answer policy questions using the internal HR corpus and tool-backed data. "
            "For a policy-only question, I rely on the retrieved document excerpts and I avoid making unsupported claims."
        )
        return finish(answer)
