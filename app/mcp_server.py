from __future__ import annotations

from typing import Any

from app.rag import EmployeeStore, PolicyRAG


class MCPToolServer:
    def __init__(self, rag: PolicyRAG, employee_store: EmployeeStore):
        self.rag = rag
        self.employee_store = employee_store

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_policy_documents",
                "description": "Search policy documents for relevant policy text.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]},
            },
            {
                "name": "get_policy_section",
                "description": "Return the exact section text for a document.",
                "inputSchema": {"type": "object", "properties": {"document_id": {"type": "string"}, "section_name": {"type": "string"}}, "required": ["document_id", "section_name"]},
            },
            {
                "name": "lookup_employee_profile",
                "description": "Retrieve a synthetic employee profile.",
                "inputSchema": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
            },
            {
                "name": "check_pto_balance",
                "description": "Return PTO balance for an employee.",
                "inputSchema": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
            },
            {
                "name": "lookup_benefits_status",
                "description": "Return benefits status and eligibility.",
                "inputSchema": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
            },
            {
                "name": "create_mock_hr_ticket",
                "description": "Create a mock HR ticket summary.",
                "inputSchema": {"type": "object", "properties": {"subject": {"type": "string"}, "summary": {"type": "string"}}, "required": ["subject", "summary"]},
            },
            {
                "name": "draft_hr_email",
                "description": "Draft a mock manager or HR message.",
                "inputSchema": {"type": "object", "properties": {"recipient": {"type": "string"}, "body": {"type": "string"}}, "required": ["recipient", "body"]},
            },
            {
                "name": "check_policy_compliance",
                "description": "Check whether a request complies with policy.",
                "inputSchema": {"type": "object", "properties": {"request_type": {"type": "string"}, "employee_id": {"type": "string"}}, "required": ["request_type"]},
            },
        ]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "search_policy_documents":
            query = arguments.get("query", "")
            top_k = arguments.get("k", 3)
            return {"results": self.rag.search(query, top_k)}

        if tool_name == "get_policy_section":
            document_id = arguments.get("document_id")
            section_name = arguments.get("section_name")
            return {"result": self.rag.get_document_section(document_id, section_name)}

        if tool_name == "lookup_employee_profile":
            employee_id = arguments.get("employee_id")
            employee = self.employee_store.get_employee(employee_id)
            if employee is None:
                return {"error": f"Employee {employee_id} not found."}
            return {"employee": employee}

        if tool_name == "check_pto_balance":
            employee_id = arguments.get("employee_id")
            employee = self.employee_store.get_employee(employee_id)
            if employee is None:
                return {"error": f"Employee {employee_id} not found."}
            return {"employee_id": employee_id, "pto_balance_days": employee.get("pto_balance_days", 0)}

        if tool_name == "lookup_benefits_status":
            employee_id = arguments.get("employee_id")
            employee = self.employee_store.get_employee(employee_id)
            if employee is None:
                return {"error": f"Employee {employee_id} not found."}
            return {
                "employee_id": employee_id,
                "status": employee.get("benefits_status"),
                "eligible": employee.get("benefits_status") == "active",
            }

        if tool_name == "create_mock_hr_ticket":
            subject = arguments.get("subject", "HR inquiry")
            summary = arguments.get("summary", "No details provided.")
            return {"ticket_id": "HR-1001", "subject": subject, "summary": summary, "status": "created"}

        if tool_name == "draft_hr_email":
            recipient = arguments.get("recipient", "manager")
            body = arguments.get("body", "This request is pending HR review.")
            return {"recipient": recipient, "body": body}

        if tool_name == "check_policy_compliance":
            request_type = arguments.get("request_type", "general")
            employee_id = arguments.get("employee_id")
            employee = self.employee_store.get_employee(employee_id)
            compliance = {"request_type": request_type, "requires_review": True, "status": "needs_manager_review"}
            if employee:
                compliance["employee_location"] = employee.get("location")
            return {"result": compliance}

        raise ValueError(f"Unknown tool: {tool_name}")
