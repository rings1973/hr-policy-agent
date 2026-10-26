"""Deterministic checks around the LLM: routing before it runs, validation after it answers.

These do not rely on the model following its prompt. A pattern router catches clear emergency,
out-of-scope and advice requests; citations are checked against what tools actually returned;
an "ok" answer with no valid evidence is replaced by a not-covered reply.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

Route = Literal["normal", "out_of_scope", "legal_advice", "sensitive_hr", "emergency"]

_ROUTES: list[tuple[Route, re.Pattern[str]]] = [
    ("emergency", re.compile(
        r"\b(suicid\w*|kill (myself|me)|self[- ]harm|in danger|being attacked|medical emergency"
        r"|call 911)\b", re.IGNORECASE)),
    ("legal_advice", re.compile(
        r"\b(legal (advice|memo|opinion)|lawsuit|sue (the company|my employer|them)|attorney"
        r"|lawyer|is (it|this) legal|tax advice|which visa|immigration advice)\b", re.IGNORECASE)),
    ("sensitive_hr", re.compile(
        r"\b(harass\w*|discriminat\w*|retaliat\w*|assault\w*|hostile work environment"
        r"|bullied|bullying)\b", re.IGNORECASE)),
    ("out_of_scope", re.compile(
        r"\b(stock price|share price|crypto\w*|bitcoin|weather|sports? scores?|recipe"
        r"|write (me )?(a )?(poem|song|story))\b", re.IGNORECASE)),
]

EMERGENCY_REPLY = (
    "If you or someone else is in immediate danger, contact local emergency services now "
    "(911 in the US). For support at work, contact People Operations through the confidential "
    "channel. This assistant cannot assess emergencies.")
OUT_OF_SCOPE_REPLY = (
    "I can only help with the company's HR policies and your HR records (PTO, remote work, "
    "expenses, benefits, leave, equipment, conduct). That question is outside what I can answer.")
NOT_COVERED_REPLY = (
    "I couldn't find this in the company's HR policies, so I won't guess. Please contact "
    "People Operations for an answer.")

_EMPLOYEE_ID = re.compile(r"\bE-?(\d{4})\b", re.IGNORECASE)


def pre_route(message: str) -> Route:
    for route, pattern in _ROUTES:
        if pattern.search(message):
            return route
    return "normal"


def resolve_employee(message: str, current: str | None) -> str | None:
    """An explicit id in the message ("I'm E-1002") switches the acting employee."""
    match = _EMPLOYEE_ID.search(message)
    return f"E-{match.group(1)}" if match else current


def parse_final(content: str) -> dict[str, Any]:
    """Parse the model's final JSON object, tolerating code fences or stray prose. If no JSON
    can be found, the whole text becomes the answer."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "answer" in data:
            return data
    return {"answer": text, "citations": [], "status": "ok", "_unparsed": True}


def validate_citations(cited: list[Any], evidence: dict[str, dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep citations whose id was returned by a tool this turn; report the rest as dropped.
    Matching ignores case so "pto_policy#notice and approval requirements" still counts."""
    by_lower = {k.lower(): k for k in evidence}
    kept, dropped, seen = [], [], set()
    for item in cited:
        key = by_lower.get(str(item).strip().lower())
        if key is None:
            dropped.append(str(item))
        elif key not in seen:
            seen.add(key)
            kept.append(evidence[key])
    return kept, dropped
