"""Web app tests: the real lifespan (MCP server subprocess on a keyless TF-IDF index) with the
agent's LLM swapped for the scripted FakeLLM from test_agent, so no API key or network is needed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import POLICY_DIR
from app.main import app
from app.rag.chunker import chunk_documents
from app.rag.embeddings import TfidfEmbedder
from app.rag.index import build_index
from app.rag.loaders import load_documents
from tests.test_agent import FakeLLM, calls, final, first_chunk_id_list


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    base = tmp_path_factory.mktemp("app_index")
    docs = load_documents(POLICY_DIR)
    build_index(docs, chunk_documents(docs), TfidfEmbedder(), base / "tfidf", POLICY_DIR)
    mp = pytest.MonkeyPatch()  # the MCP subprocess inherits these
    for key, value in {"INDEX_DIR": str(base), "EMBEDDING_BACKEND": "tfidf",
                       "REFERENCE_DATE": "2026-10-22", "MIN_SCORE": ""}.items():
        mp.setenv(key, value)
    mp.setattr("app.config.INDEX_DIR", base)  # read in-process by /health's index info
    mp.setattr("app.config.EMBEDDING_BACKEND", "tfidf")
    with TestClient(app) as test_client:
        yield test_client
    mp.undo()


def use_llm(client, llm):
    client.app.state.hr.agent.llm = llm


def test_health_reports_mcp_connection(client):
    body = client.get("/health").json()
    assert body["mcp"]["connected"] is True and body["mcp"]["tool_count"] == 10
    assert body["status"] in {"ok", "degraded"}  # degraded only when no LLM key (CI)


def test_page_and_catalog_endpoints(client):
    page = client.get("/")
    assert page.status_code == 200 and "HR Policy Agent" in page.text
    assert "innerHTML" not in page.text  # model output is rendered with textContent only
    assert {t["name"] for t in client.get("/tools").json()["tools"]} >= {
        "search_policy_documents", "project_pto_balance", "create_mock_hr_ticket"}
    ids = {e["employee_id"] for e in client.get("/employees").json()["employees"]}
    groups = client.get("/demo-tasks").json()["groups"]
    questions = [q for g in groups for q in g["questions"]]
    assert len(questions) >= 20
    assert {q["employee_id"] for q in questions} - {None} <= ids


def test_chat_returns_cited_answer_and_trace(client):
    use_llm(client, FakeLLM(calls(("search_policy_documents", {"query": "carryover"})),
                            final(answer="Up to 5 days.", citations=first_chunk_id_list)))
    body = client.post("/chat", json={"message": "How much PTO carries over?"}).json()
    assert body["status"] == "ok" and body["citations"] and body["session_id"]
    assert "search_policy_documents" in [s["name"] for s in body["tool_trace"]]


def test_picker_sets_identity_for_scoping(client):
    llm = FakeLLM(calls(("check_pto_balance", {"employee_id": "E-1001"})),
                  final(answer="Only your own records.", status="clarify"))
    use_llm(client, llm)
    body = client.post("/chat", json={"message": "What's my coworker's balance?",
                                      "employee_id": "e-1002"}).json()
    assert body["employee_id"] == "E-1002"
    assert body["tool_trace"][2]["ok"] is False  # E-1001's record was refused


def test_confirm_flow_creates_ticket_once(client):
    use_llm(client, FakeLLM(calls(("create_mock_hr_ticket", {
        "employee_id": "E-1002", "category": "pto", "subject": "PTO", "summary": "3 days"})),
        final(answer="Proposed.")))
    body = client.post("/chat", json={"message": "open a ticket", "employee_id": "E-1002"}).json()
    assert body["status"] == "pending_confirmation"
    token, sid = body["pending_action"]["token"], body["session_id"]
    done = client.post("/chat/confirm", json={"session_id": sid, "token": token,
                                              "approve": True}).json()
    assert done["status"] == "ok" and "HR-0" in done["answer"]
    again = client.post("/chat/confirm", json={"session_id": sid, "token": token,
                                               "approve": True}).json()
    assert again["status"] == "error"


def test_out_of_scope_needs_no_model(client):
    use_llm(client, FakeLLM())  # any LLM call would fail the test
    body = client.post("/chat", json={"message": "What is the stock price today?"}).json()
    assert body["status"] == "escalate"


def test_health_and_eval_endpoints_report_build_info(client):
    index = client.get("/health").json()["index"]
    assert index["embedder"] == "tfidf" and index["chunks"] > 0
    assert isinstance(client.get("/eval/latest").json(), dict)
