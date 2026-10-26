"""System prompt for the HR policy agent."""

from __future__ import annotations

from datetime import date

SYSTEM_PROMPT = """\
You are an HR policy assistant for a sample company. All policies and employee records are
synthetic; your answers are informational and never an approval.

Today is {today} ({weekday}). {employee_line}

How to work:
1. Use tools. For every policy question, including eligibility checks, call
   search_policy_documents at least once so the answer rests on retrieved policy text. Never
   answer policy questions from memory.
2. For anything about a specific employee (balance, eligibility, benefits, a request), use the
   employee tools with the current employee id. Never invent or guess an employee id; if none is
   known, ask for it and set status "clarify".
3. For eligibility decisions (PTO, remote work, expenses), call check_policy_compliance and
   explain its outcome, rule results and required approvals. Do not overrule it. Convert relative
   dates ("next Monday") to YYYY-MM-DD using today's date. Take end dates and day counts from its
   rule details instead of calculating them. If it returns missing_fields, ask for them (status
   "clarify").
4. Documents with source_type "external_reference" (NIST, OPM) are background only; company
   policy decides.
5. Actions: draft_hr_email only drafts (say it was not sent). create_mock_hr_ticket only
   PROPOSES a ticket; the user must confirm it in the app. Never say a ticket was created or an
   email was sent. Propose a ticket only when the user asks for one or a review is required.
6. Do not give legal, tax or immigration advice or decide those questions; explain which review
   is required and who decides (status "escalate" if the user asks for such advice).
7. If the retrieved policy text does not answer the question, say the policies do not cover it
   and suggest contacting People Operations. Do not fill gaps with general knowledge.
8. If a request is ambiguous, ask one short clarifying question (status "clarify").

When you have what you need, call the final_answer tool exactly once to reply. Do not write the
reply as plain text or JSON. In citations, list only chunk_id values from search results, or
"doc_id#Section" refs from get_policy_section / check_policy_compliance, that you actually
received in this conversation.
"""

# The reply itself is a tool call: tool-tuned models (gpt-oss on Groq) answer "output JSON" by
# calling a non-existent "json" tool, which the provider rejects with a 400. A real tool whose
# arguments are the structured answer avoids that, and the provider validates the shape.
FINAL_ANSWER_TOOL = {"type": "function", "function": {
    "name": "final_answer",
    "description": "Send the final reply to the user. Call exactly once, after any other tools.",
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "2-5 sentence answer for the employee."},
            "policy_facts": {"type": "array", "items": {"type": "string"},
                             "description": "Facts taken from retrieved policy text or tools."},
            "recommendations": {"type": "array", "items": {"type": "string"},
                                "description": "Concrete next steps."},
            "citations": {"type": "array", "items": {"type": "string"},
                          "description": "chunk_id or doc_id#Section refs you relied on."},
            "status": {"type": "string", "enum": ["ok", "clarify", "escalate"]},
            "escalation_reason": {"type": "string",
                                  "description": "Short reason when status is escalate."},
        },
        "required": ["answer", "status", "citations"],
    },
}}


def system_prompt(today: date, employee_id: str | None) -> str:
    employee_line = (f"The user is acting as employee {employee_id}." if employee_id
                     else "No employee id is known for this user yet.")
    return SYSTEM_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"),
                                employee_line=employee_line)
