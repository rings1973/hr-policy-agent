"""End-to-end tests of hr_mcp.server over a real stdio ClientSession (subprocess, JSON-RPC).

The server gets a freshly built keyless TF-IDF index and a pinned REFERENCE_DATE through its
environment, so these tests need no API key and give the same decisions on any day.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from app.config import BASE_DIR, POLICY_DIR
from app.rag.chunker import chunk_documents
from app.rag.embeddings import TfidfEmbedder
from app.rag.index import build_index
from app.rag.loaders import load_documents

EXPECTED_TOOLS = {
    "search_policy_documents", "get_policy_section", "list_policy_documents",
    "lookup_employee_profile", "check_pto_balance", "project_pto_balance",
    "lookup_benefits_status", "check_policy_compliance", "draft_hr_email", "create_mock_hr_ticket",
}


@pytest.fixture(scope="module")
def server_params(tmp_path_factory):
    base = tmp_path_factory.mktemp("mcp_index")
    docs = load_documents(POLICY_DIR)
    build_index(docs, chunk_documents(docs), TfidfEmbedder(), base / "tfidf", POLICY_DIR)
    env = {**os.environ, "INDEX_DIR": str(base), "EMBEDDING_BACKEND": "tfidf",
           "REFERENCE_DATE": "2026-10-22", "MIN_SCORE": ""}
    return StdioServerParameters(command=sys.executable, args=["-m", "hr_mcp.server"],
                                 env=env, cwd=str(BASE_DIR))


def run(params: StdioServerParameters, scenario: Callable[[ClientSession], Awaitable[None]]):
    async def main() -> None:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            await scenario(session)
    anyio.run(main)


def call(session: ClientSession, name: str, **arguments):
    return session.call_tool(name, arguments, read_timeout_seconds=30)


def test_initialize_and_list_tools(server_params):
    async def scenario(session):
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == EXPECTED_TOOLS
        assert tools["lookup_employee_profile"].annotations.read_only_hint is True
        assert "employee_id" in tools["check_policy_compliance"].input_schema["required"]
    run(server_params, scenario)


def test_data_tools_and_errors(server_params):
    async def scenario(session):
        profile = await call(session, "lookup_employee_profile", employee_id="E-1001")
        assert not profile.is_error
        assert profile.structured_content["manager"]["name"] == "Jordan Rivera"

        unknown = await call(session, "lookup_employee_profile", employee_id="E-9999")
        assert unknown.is_error and "E-9999" in unknown.content[0].text  # ToolError text shown

        bad_date = await call(session, "check_policy_compliance", request_type="pto",
                              employee_id="E-1002", days=3, start_date="next week")
        assert bad_date.is_error and "YYYY-MM-DD" in bad_date.content[0].text

        decision = await call(session, "check_policy_compliance", request_type="remote_work",
                              employee_id="E-1001", days=42, destination_country="Mexico")
        result = decision.structured_content
        assert result["outcome"] == "needs_review"
        assert {"Tax review", "Immigration review"} <= set(result["required_approvals"])
        assert result["evaluated_on"] == "2026-10-22"

        email = await call(session, "draft_hr_email", recipient_id="M-42",
                           subject="PTO", body="Requesting 3 days.")
        assert email.structured_content["status"] == "draft_not_sent"
        mine = await call(session, "draft_hr_email", recipient_id="manager", employee_id="E-1002",
                          subject="PTO", body="Requesting 3 days.")
        assert mine.structured_content["draft"]["to"]["id"] == "M-42"
        orphan = await call(session, "draft_hr_email", recipient_id="MANAGER", subject="s",
                            body="b")
        assert orphan.is_error and "needs employee_id" in orphan.content[0].text

        projection = await call(session, "project_pto_balance", employee_id="E-1002",
                                target_date="2027-12-15")
        assert projection.structured_content["projected_available"] == 19.17
    run(server_params, scenario)


def test_policy_retrieval_tools(server_params):
    async def scenario(session):
        found = await call(session, "search_policy_documents", query="work from another state",
                           k=3, include_external=False)
        results = found.structured_content["results"]
        assert results[0]["doc_id"] == "remote_work_policy"
        assert all(r["source_type"] == "company_policy" for r in results)

        section = await call(session, "get_policy_section", document_id="pto_policy",
                             section="notice and approval requirements")
        assert "10 business days" in section.structured_content["text"]

        docs = await call(session, "list_policy_documents")
        assert len(docs.structured_content["documents"]) == 12
    run(server_params, scenario)


def test_ticket_needs_confirmation_and_token_is_single_use(server_params):
    async def scenario(session):
        args = {"employee_id": "E-1001", "category": "remote_work",
                "subject": "Remote work from Mexico City", "summary": "42 days from 2026-12-01."}
        proposed = (await call(session, "create_mock_hr_ticket", **args)).structured_content
        assert proposed["status"] == "pending_confirmation" and "ticket_id" not in proposed

        swapped = await call(session, "create_mock_hr_ticket", **{**args, "subject": "Other"},
                             confirmation_token=proposed["token"])
        assert swapped.is_error  # a token only confirms the request it was issued for

        created = await call(session, "create_mock_hr_ticket", **args,
                             confirmation_token=proposed["token"])
        assert created.structured_content["status"] == "created"
        assert created.structured_content["ticket_id"] == "HR-0003"

        reused = await call(session, "create_mock_hr_ticket", **args,
                            confirmation_token=proposed["token"])
        assert reused.is_error and "already used" in reused.content[0].text
    run(server_params, scenario)
