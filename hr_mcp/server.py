"""MCP server for the HR policy agent: 10 tools over policy retrieval, mock HR data, rule checks
and mock actions.

    python -m hr_mcp.server                              stdio (launched by the agent)
    python -m hr_mcp.server --transport streamable-http  HTTP on MCP_HTTP_PORT (default 8765)
    mcp dev hr_mcp/server.py                             MCP Inspector

With stdio, stdout carries JSON-RPC, so nothing here may print to stdout; warnings go to stderr.
Anticipated failures (unknown id, bad date, invalid token) are raised as ToolError so the message
reaches the model with is_error=True; any other exception reaches it only as a generic error.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from functools import cache
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from app import config
from app.rag import PolicyIndex, open_index
from app.rag.loaders import COMPANY_POLICY
from hr_mcp import rules
from hr_mcp.data_store import HRDataStore, NotFound

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
MOCK_ACTION = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

EmployeeId = Annotated[str, Field(description="Synthetic employee id, e.g. E-1001.")]
TicketCategory = Literal["pto", "remote_work", "expense", "benefits", "conduct", "leave", "other"]

mcp = MCPServer(
    "hr-policy-tools",
    version="1.0.0",
    instructions=(
        "Tools for a synthetic HR policy assistant. Search or read policy text before answering "
        "policy questions and cite the chunk_id or document section. Use the employee tools for "
        "personal facts and check_policy_compliance for eligibility decisions instead of judging "
        "them yourself. Emails are drafts only and tickets need the user's confirmation."
    ),
)


@cache
def store() -> HRDataStore:
    return HRDataStore(config.MOCK_DATA_DIR)


@cache
def index() -> PolicyIndex:
    return open_index(config.INDEX_DIR, config.EMBEDDING_BACKEND, config.GEMINI_API_KEY,
                      config.MIN_SCORE)


def today() -> date:
    return date.fromisoformat(config.REFERENCE_DATE) if config.REFERENCE_DATE else date.today()


@contextmanager
def tool_errors() -> Iterator[None]:
    """Turn the domain errors of data_store/rules into messages the model can read."""
    try:
        yield
    except (NotFound, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def parse_date(value: str | None, field: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ToolError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


# Policy retrieval (RAG) ------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def search_policy_documents(
    query: Annotated[str, Field(description="Natural-language policy question or keywords.")],
    k: Annotated[int, Field(ge=1, le=10, description="Number of chunks to return.")] = 4,
    document_id: Annotated[str | None, Field(
        description="Restrict to one document, e.g. remote_work_policy.")] = None,
    include_external: Annotated[bool, Field(
        description="Include public external references (NIST, OPM), not only company "
                    "policy.")] = True,
) -> dict[str, Any]:
    """Semantic search over the HR policy corpus. Returns the best-matching chunks with their
    chunk_id, document, section, page and score. weak_evidence=true means no chunk scored above
    the relevance threshold: say the policies may not cover the question rather than guess."""
    source_type = None if include_external else COMPANY_POLICY
    hits = index().search(query, k=k, document_id=document_id, source_type=source_type)
    results = [
        {"chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title, "section": h.section,
         "page": h.page, "source_type": h.source_type, "source_url": h.source_url,
         "snippet": h.snippet, "text": h.text, "score": round(h.score, 4), "weak": h.weak}
        for h in hits
    ]
    return {"query": query, "results": results,
            "weak_evidence": not results or all(h.weak for h in hits)}


@mcp.tool(annotations=READ_ONLY)
def get_policy_section(
    document_id: Annotated[str, Field(description="Document id, e.g. pto_policy.")],
    section: Annotated[str, Field(description="Exact section heading (case-insensitive), "
                                              "e.g. 'Notice and Approval Requirements'.")],
) -> dict[str, Any]:
    """Return the full text of one policy section, e.g. to read a rule cited by
    check_policy_compliance (its policy_ref is "document_id#Section")."""
    found = index().get_section(document_id, section)
    if found is None:
        docs = {d["doc_id"] for d in index().list_documents()}
        hint = "" if document_id in docs else f" Known documents: {', '.join(sorted(docs))}."
        raise ToolError(f"No section {section!r} in document {document_id!r}.{hint}")
    return found


@mcp.tool(annotations=READ_ONLY)
def list_policy_documents() -> dict[str, Any]:
    """List the policy documents with their title, format and source type
    (company_policy or external_reference)."""
    return {"documents": [
        {"doc_id": d["doc_id"], "title": d["title"], "format": d["format"],
         "source_type": d["source_type"], "source_url": d.get("source_url")}
        for d in index().list_documents()
    ]}


# Mock HR records -------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def lookup_employee_profile(employee_id: EmployeeId) -> dict[str, Any]:
    """Synthetic employee profile: role, employment type, hire date, home state/country, remote
    eligibility, security training, plus the manager's name and email."""
    with tool_errors():
        profile = store().employee(employee_id)
        profile["manager"] = store().manager(profile["manager_id"])
    return profile


@mcp.tool(annotations=READ_ONLY)
def check_pto_balance(employee_id: EmployeeId) -> dict[str, Any]:
    """PTO balance in days: annual entitlement, carryover, used, pending, available, and whether
    PTO can be used yet (eligible_to_use)."""
    with tool_errors():
        balance = store().pto(employee_id)
    return {**balance, "unit": "days", "as_of": store().as_of}


@mcp.tool(annotations=READ_ONLY)
def project_pto_balance(
    employee_id: EmployeeId,
    target_date: Annotated[str, Field(description="Future date, YYYY-MM-DD.")],
) -> dict[str, Any]:
    """Estimate how many PTO days an employee will have on a future date if no more PTO is used:
    accrual per pay period by tenure tier, the 5-day year-end carryover cap and the 31 March
    expiry of carried-over days. Returns projected_available, the days forfeited or expired on
    the way, dated events and the assumptions. Use it instead of calculating accrual yourself."""
    target = parse_date(target_date, "target_date")
    with tool_errors():
        employee, balance = store().employee(employee_id), store().pto(employee_id)
    as_of = date.fromisoformat(store().as_of)
    if target.year > as_of.year + 5:
        raise ToolError("target_date must be within 5 years of the balance date.")
    return rules.project_pto(employee, balance, as_of, target)


@mcp.tool(annotations=READ_ONLY)
def lookup_benefits_status(employee_id: EmployeeId) -> dict[str, Any]:
    """Benefits enrollment: status (active, pending, not_eligible), medical/dental/vision
    elections, 401(k) contribution and any enrollment deadline."""
    with tool_errors():
        return store().benefits(employee_id)


# Rule checks -----------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def check_policy_compliance(
    request_type: Literal["pto", "remote_work", "expense"],
    employee_id: EmployeeId,
    days: Annotated[float | None, Field(
        ge=0, description="PTO business days, or remote-work calendar days.")] = None,
    start_date: Annotated[str | None, Field(description="First day, YYYY-MM-DD.")] = None,
    destination_state: Annotated[str | None, Field(
        description="US state code for remote work, e.g. CO.")] = None,
    destination_country: Annotated[str | None, Field(
        description="Country for remote work, e.g. Mexico. Omit for the US.")] = None,
    expense_category: rules.ExpenseCategory | None = None,
    amount: Annotated[float | None, Field(ge=0, description="Expense amount in USD.")] = None,
) -> dict[str, Any]:
    """Check a PTO, remote-work or expense request against the policy rules and the employee's
    records. Returns outcome (allowed, allowed_with_approval, needs_review, needs_info,
    not_allowed), every rule applied with its policy_ref, required_approvals and missing_fields.
    Use this for eligibility decisions; ask the user for any missing_fields."""
    with tool_errors():
        employee = store().employee(employee_id)
        start = parse_date(start_date, "start_date")
        if request_type == "pto":
            decision = rules.check_pto(employee, store().pto(employee_id), days, start, today())
        elif request_type == "remote_work":
            decision = rules.check_remote(
                employee, None if days is None else int(days), destination_state,
                destination_country, start, today())
        else:
            decision = rules.check_expense(employee, expense_category, amount)
    return {**decision.to_dict(), "evaluated_on": today().isoformat()}


# Mock actions ----------------------------------------------------------------------------


@mcp.tool(annotations=MOCK_ACTION)
def draft_hr_email(
    recipient_id: Annotated[str, Field(
        description="MANAGER (the employee's own manager), an employee id, a manager id "
                    "(e.g. M-42) or PEOPLE-OPS.")],
    subject: str,
    body: str,
    employee_id: Annotated[str | None, Field(
        description="The employee writing; required when recipient_id is MANAGER.")] = None,
) -> dict[str, Any]:
    """Draft an email to a manager, employee or People Operations for the user to review. It is
    never sent: the result has status draft_not_sent."""
    with tool_errors():
        if recipient_id.strip().upper() == "MANAGER":
            if not employee_id:
                raise ToolError("recipient_id MANAGER needs employee_id.")
            recipient_id = store().employee(employee_id)["manager_id"]
        recipient = store().recipient(recipient_id)
    return {"status": "draft_not_sent",
            "draft": {"to": recipient, "subject": subject, "body": body}}


@mcp.tool(annotations=MOCK_ACTION)
def create_mock_hr_ticket(
    employee_id: EmployeeId,
    category: TicketCategory,
    subject: str,
    summary: str,
    confirmation_token: Annotated[str | None, Field(
        description="Set only by the application after the user confirms.")] = None,
) -> dict[str, Any]:
    """Create a mock HR ticket in two steps. Without a token it returns
    status=pending_confirmation with a preview; nothing is created until the user confirms.
    Tickets are mock records held in memory and sent nowhere."""
    with tool_errors():
        employee = store().employee(employee_id)
        payload = {"employee_id": employee["employee_id"], "category": category,
                   "subject": subject, "summary": summary}
        if confirmation_token is None:
            action = store().propose("ticket", payload)
            return {"status": "pending_confirmation", "token": action.token,
                    "expires_at": action.expires_at.isoformat(timespec="seconds"),
                    "preview": payload}
        store().confirm(confirmation_token, "ticket", payload)
        ticket = store().add_ticket(payload)
    return {"status": "created", "ticket_id": ticket["ticket_id"], "ticket": ticket}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the HR policy MCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host="0.0.0.0", port=int(os.getenv("MCP_HTTP_PORT", "8765")))


if __name__ == "__main__":
    main()
