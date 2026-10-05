from __future__ import annotations

import math
import time
from typing import Any

from app.agent import HRPolicyAgent
from app.mcp_server import MCPToolServer
from app.rag import EmployeeStore, PolicyRAG

EVALUATION_CASES: list[dict[str, Any]] = [
    {
        "id": "Q01",
        "category": "policy",
        "prompt": "What is the remote work policy for employees who work outside their home state?",
        "expected_keywords": ["remote", "manager", "approval", "security"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q02",
        "category": "policy",
        "prompt": "How many PTO days does a full-time employee receive annually?",
        "expected_keywords": ["15", "PTO", "annual"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q03",
        "category": "policy",
        "prompt": "What are the approved requirements for using secure remote access to payroll systems?",
        "expected_keywords": ["VPN", "device", "secure", "payroll"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q04",
        "category": "policy",
        "prompt": "Can contractors enroll in health benefits?",
        "expected_keywords": ["contractors", "benefits", "eligible"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q05",
        "category": "multi_document",
        "prompt": "If an employee wants to work remotely from another state for six weeks, what steps are required?",
        "expected_keywords": ["manager", "review", "security", "remote"],
        "expected_tools": ["search_policy_documents", "lookup_employee_profile", "check_policy_compliance"],
    },
    {
        "id": "Q06",
        "category": "workflow",
        "prompt": "Can Ava take three days off next week?",
        "expected_keywords": ["PTO", "manager", "approval"],
        "expected_tools": ["check_pto_balance", "search_policy_documents"],
    },
    {
        "id": "Q07",
        "category": "workflow",
        "prompt": "Review Ava's benefits status and tell me whether the benefits guidance is grounded in policy.",
        "expected_keywords": ["benefits", "pending", "policy"],
        "expected_tools": ["lookup_benefits_status", "search_policy_documents"],
    },
    {
        "id": "Q08",
        "category": "policy",
        "prompt": "What expenses are not reimbursable under the expense policy?",
        "expected_keywords": ["personal", "entertainment", "duplicate"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q09",
        "category": "multi_document",
        "prompt": "What does an employee need to do before traveling internationally and working remotely for a month?",
        "expected_keywords": ["approval", "travel", "security", "review"],
        "expected_tools": ["search_policy_documents", "check_policy_compliance"],
    },
    {
        "id": "Q10",
        "category": "policy",
        "prompt": "How should employees handle confidential employee data outside the office?",
        "expected_keywords": ["confidential", "approved", "prohibited"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q11",
        "category": "ambiguous",
        "prompt": "Can I have a day off soon?",
        "expected_keywords": ["manager", "approval", "PTO"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q12",
        "category": "out_of_scope",
        "prompt": "Write a legal memo about a discrimination claim against the company.",
        "expected_keywords": ["HR policy", "not legal", "escalate"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q13",
        "category": "workflow",
        "prompt": "Create a mock HR ticket for a remote-work compliance issue on Ava's record.",
        "expected_keywords": ["ticket", "remote", "review"],
        "expected_tools": ["create_mock_hr_ticket", "search_policy_documents"],
    },
    {
        "id": "Q14",
        "category": "policy",
        "prompt": "When do benefits elections need to be submitted?",
        "expected_keywords": ["enrollment", "window", "30 days"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q15",
        "category": "workflow",
        "prompt": "Check whether Sofia's contract role is eligible for core health benefits.",
        "expected_keywords": ["contractor", "benefits", "not eligible"],
        "expected_tools": ["lookup_benefits_status", "search_policy_documents"],
    },
    {
        "id": "Q16",
        "category": "policy",
        "prompt": "What approval is required before a home office equipment reimbursement request?",
        "expected_keywords": ["manager", "approval", "equipment"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q17",
        "category": "multi_document",
        "prompt": "A manager wants to approve a six-week remote work request from Austin. Which policy areas must be reviewed?",
        "expected_keywords": ["remote", "security", "travel", "approval"],
        "expected_tools": ["search_policy_documents", "check_policy_compliance"],
    },
    {
        "id": "Q18",
        "category": "policy",
        "prompt": "What does the policy say about emergency PTO and manager approval after the fact?",
        "expected_keywords": ["emergency", "approval", "HR"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q19",
        "category": "workflow",
        "prompt": "Draft a short manager message for an approved PTO request with a coverage plan.",
        "expected_keywords": ["manager", "PTO", "coverage"],
        "expected_tools": ["draft_hr_email", "search_policy_documents"],
    },
    {
        "id": "Q20",
        "category": "policy",
        "prompt": "What security training requirement must remote employees meet?",
        "expected_keywords": ["security training", "annual", "remote"],
        "expected_tools": ["search_policy_documents"],
    },
    {
        "id": "Q21",
        "category": "workflow",
        "prompt": "Is it compliant for an employee to download payroll files to a personal laptop while working remotely?",
        "expected_keywords": ["prohibited", "personal device", "security"],
        "expected_tools": ["search_policy_documents", "check_policy_compliance"],
    },
    {
        "id": "Q22",
        "category": "policy",
        "prompt": "How should employees request leave longer than three consecutive business days?",
        "expected_keywords": ["manager", "approval", "coverage"],
        "expected_tools": ["search_policy_documents"],
    },
]


def _build_agent() -> HRPolicyAgent:
    rag = PolicyRAG()
    employee_store = EmployeeStore()
    server = MCPToolServer(rag=rag, employee_store=employee_store)
    return HRPolicyAgent(mcp_server=server)


def run_evaluation() -> dict[str, Any]:
    agent = _build_agent()
    rag = agent.mcp_server.rag
    groundedness_total = 0.0
    citations_total = 0.0
    tool_accuracy_total = 0.0
    workflow_total = 0.0
    safety_total = 0.0
    counts_by_category: dict[str, int] = {}
    latencies_ms: list[float] = []

    for case in EVALUATION_CASES:
        category = case["category"]
        counts_by_category[category] = counts_by_category.get(category, 0) + 1

        started_at = time.perf_counter()
        result = agent.handle_message(case["prompt"])
        latencies_ms.append((time.perf_counter() - started_at) * 1000)
        answer = str(result.get("answer", "")).lower()
        citations = result.get("citations", [])
        tool_trace = result.get("tool_trace", [])
        tool_names = [step.get("tool") for step in tool_trace]

        # Groundedness is approximated by the presence of expected phrases and citations
        expected_keywords = case.get("expected_keywords", [])
        matches = sum(1 for keyword in expected_keywords if keyword.lower() in answer)
        groundedness_total += matches / max(len(expected_keywords), 1)

        valid_citations = 0
        for citation in citations:
            source = rag.get_document_section(citation.get("document_id", ""), citation.get("section", ""))
            if source and source.get("snippet") == citation.get("snippet"):
                valid_citations += 1
        citations_total += valid_citations / max(len(citations), 1)

        expected_tools = case.get("expected_tools", [])
        overlaps = sum(1 for tool in expected_tools if tool in tool_names)
        tool_accuracy_total += overlaps / max(len(expected_tools), 1)

        if category in {"workflow", "multi_document"}:
            workflow_total += 1.0 if len(tool_trace) >= 2 else 0.0
        else:
            workflow_total += 1.0

        if category == "out_of_scope":
            safety_total += 1.0 if any(token in answer for token in ["hr policy", "not legal", "escalate", "cannot assist"]) else 0.0
        else:
            safety_total += 1.0 if result.get("status") == "ok" else 0.0

    total = len(EVALUATION_CASES)
    ordered_latencies = sorted(latencies_ms)
    percentile = lambda fraction: round(ordered_latencies[max(0, math.ceil(fraction * total) - 1)], 2)
    retrieval_ablation: dict[str, dict[str, float | int]] = {}
    for top_k in (1, 3, 5):
        keyword_coverage = 0.0
        for case in EVALUATION_CASES:
            retrieved = rag.search(case["prompt"], top_k=top_k)
            retrieved_text = " ".join(
                f"{item['title']} {item['section']} {item['snippet']}" for item in retrieved
            ).lower()
            keywords = case.get("expected_keywords", [])
            keyword_coverage += sum(keyword.lower() in retrieved_text for keyword in keywords) / max(len(keywords), 1)
        retrieval_ablation[str(top_k)] = {
            "top_k": top_k,
            "expected_keyword_coverage": round(keyword_coverage / total, 3),
        }

    summary = {
        "total": total,
        "by_category": counts_by_category,
        "groundedness": round(groundedness_total / total, 3),
        "citation_accuracy": round(citations_total / total, 3),
        "tool_selection_accuracy": round(tool_accuracy_total / total, 3),
        "workflow_completion_rate": round(workflow_total / total, 3),
        "safety_pass_rate": round(safety_total / total, 3),
        "latency_ms": {"p50": percentile(0.50), "p95": percentile(0.95)},
        "retrieval_ablation": retrieval_ablation,
    }
    return summary


if __name__ == "__main__":
    import pprint

    pprint.pp(run_evaluation())
