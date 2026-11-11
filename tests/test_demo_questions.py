"""The demo question library computes its request dates from today. These tests run the real
rules engine on those dates for every day over five months, so a question can never again ask
about a date that has passed or that gives a different outcome from the one it promises."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import demo_questions
from app.config import MOCK_DATA_DIR
from hr_mcp import rules
from hr_mcp.data_store import HRDataStore

DAYS = [date(2026, 11, 11) + timedelta(days=n) for n in range(150)]


@pytest.fixture(scope="module")
def store() -> HRDataStore:
    return HRDataStore(MOCK_DATA_DIR)


def pto(store: HRDataStore, emp: str, days: float, start: date, today: date) -> rules.Decision:
    return rules.check_pto(store.employee(emp), store.pto(emp), days, start, today)


def results(decision: rules.Decision) -> dict[str, str]:
    return {hit.rule: hit.result for hit in decision.rule_hits}


@pytest.mark.parametrize("today", DAYS, ids=str)
def test_question_dates_keep_their_outcomes(store: HRDataStore, today: date) -> None:
    d = demo_questions.request_dates(today)
    assert all(day > today for day in d.values())
    assert d["pto"].weekday() == d["domestic"].weekday() == d["abroad"].weekday() == 0

    # Demo 2: 3 days for E-1002 are allowed, pending only the manager's approval.
    demo = pto(store, "E-1002", 3, d["pto"], today)
    assert demo.outcome == "allowed_with_approval" and results(demo)["notice"] == "pass"
    # Too little notice: the same request 2 business days out fails on notice alone.
    rushed = results(pto(store, "E-1002", 3, d["short"], today))
    assert rushed["notice"] == "fail" and rushed["balance"] == "pass"
    # Over the balance: E-1005 has 2 days; notice is fine, so the balance is the reason.
    over = pto(store, "E-1005", 3, d["pto"], today)
    assert over.outcome == "not_allowed"
    assert results(over)["balance"] == "fail" and results(over)["notice"] == "pass"
    # Interns are outside the PTO policy whatever the date.
    assert pto(store, "E-1008", 2, d["pto"], today).outcome == "not_allowed"
    # New hire: refused, and the library's stated reason matches the rule that fails.
    new_hire = pto(store, "E-1004", 2, d["pto"], today)
    assert new_hire.outcome == "not_allowed"
    expect = next(q["expect"] for _, qs in demo_questions.groups(today) for q in qs
                  if q["label"] == "New hire asks for PTO")
    wait = results(new_hire)["new_hire_wait"]
    assert ("90-day new-hire wait ends" in expect) == (wait == "fail")

    # Demo 1: 6 weeks in Mexico needs review (international > 30 days), not a refusal.
    abroad = rules.check_remote(store.employee("E-1001"), 42, None, "Mexico", d["abroad"], today)
    assert abroad.outcome == "needs_review"
    # Remote work without security training stays refused.
    oregon = rules.check_remote(store.employee("E-1004"), 21, "OR", None, d["domestic"], today)
    assert oregon.outcome == "not_allowed" and results(oregon)["security_training"] == "fail"


def test_prompts_carry_the_computed_dates() -> None:
    today = date(2026, 11, 11)
    d = demo_questions.request_dates(today)
    prompts = {q["label"]: q["prompt"] for _, qs in demo_questions.groups(today) for q in qs}
    assert "Monday, November 30, 2026" in prompts["3 days of PTO + manager email"]
    assert d["pto"] == date(2026, 11, 30) and d["short"] == date(2026, 11, 13)
    assert "Monday, January 11, 2027" in prompts["Remote work from Mexico City"]
