from app.main import agent, app
from app.rag import PolicyRAG
from fastapi.testclient import TestClient

client = TestClient(app)


def test_tool_catalog_has_required_tools():
    tool_names = {tool["name"] for tool in agent.mcp_server.list_tools()}
    required = {
        "search_policy_documents",
        "get_policy_section",
        "lookup_employee_profile",
        "check_pto_balance",
        "lookup_benefits_status",
        "create_mock_hr_ticket",
        "draft_hr_email",
        "check_policy_compliance",
    }
    assert required.issubset(tool_names)


def test_employee_lookup_tool_call():
    payload = agent.mcp_server.call_tool("lookup_employee_profile", {"employee_id": "E-1001"})
    employee = payload["employee"]
    assert employee["employee_id"] == "E-1001"
    assert employee["remote_work_eligible"] is True


def test_mcp_http_initialize_discovery_and_tool_call():
    initialized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["capabilities"]["tools"] == {}

    discovery = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = {tool["name"] for tool in discovery.json()["result"]["tools"]}
    assert "search_policy_documents" in tool_names

    call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "lookup_employee_profile", "arguments": {"employee_id": "E-1001"}},
        },
    )
    assert call.status_code == 200
    assert call.json()["result"]["structuredContent"]["employee"]["name"] == "Ava Patel"


def test_policy_rag_indexes_markdown_and_text_sources(tmp_path):
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "remote.md").write_text("# Remote Policy\n\n## Secure Access\nUse approved VPN access.", encoding="utf-8")
    (policy_dir / "onboarding.txt").write_text("New hires receive an equipment checklist.", encoding="utf-8")

    rag = PolicyRAG(policy_dir=policy_dir, index_file=tmp_path / "index.sqlite3")

    assert {chunk.document_id for chunk in rag.chunks} == {"remote.md", "onboarding.txt"}
    assert rag.search("VPN access", top_k=1)[0]["document_id"] == "remote.md"
    assert (tmp_path / "index.sqlite3").is_file()
