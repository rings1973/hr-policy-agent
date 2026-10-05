from app.main import agent


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
