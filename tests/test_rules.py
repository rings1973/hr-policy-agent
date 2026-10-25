"""Table-driven tests for hr_mcp.rules and the mock data store (no MCP, no network)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.config import MOCK_DATA_DIR, POLICY_DIR
from app.rag.loaders import load_documents
from hr_mcp import rules
from hr_mcp.data_store import HRDataStore, NotFound

TODAY = date(2026, 10, 22)  # a Thursday; the as_of date of mock_data/


@pytest.fixture(scope="module")
def store():
    return HRDataStore(MOCK_DATA_DIR)


def pto(store, eid, days, start):
    return rules.check_pto(store.employee(eid), store.pto(eid), days,
                           date.fromisoformat(start) if start else None, TODAY)


def remote(store, eid, days, state=None, country=None, start=None):
    return rules.check_remote(store.employee(eid), days, state, country,
                              date.fromisoformat(start) if start else None, TODAY)


def hits(decision):
    return {h.rule: h.result for h in decision.rule_hits}


@pytest.mark.parametrize(("eid", "days", "start", "outcome", "rule", "result"), [
    # Demo 2: 3 days with 7 available and 7 business days' notice.
    ("E-1002", 3, "2026-11-02", "allowed_with_approval", "notice", "pass"),
    ("E-1004", 2, "2026-11-16", "not_allowed", "new_hire_wait", "fail"),   # 90-day wait
    ("E-1005", 3, "2026-11-16", "not_allowed", "balance", "fail"),         # 2 days available
    ("E-1001", 5, "2026-11-02", "not_allowed", "notice", "fail"),          # >3 days needs 10
    ("E-1001", 5, "2026-11-16", "allowed_with_approval", "coverage_plan", "action_required"),
    ("E-1003", 2, "2026-11-16", "not_allowed", "employment_type", "fail"),  # contractor
    ("E-1008", 2, "2026-11-16", "not_allowed", "employment_type", "fail"),  # intern
    ("E-1002", None, None, "needs_info", "new_hire_wait", "pass"),
])
def test_pto_rules(store, eid, days, start, outcome, rule, result):
    decision = pto(store, eid, days, start)
    assert decision.outcome == outcome
    assert hits(decision)[rule] == result


def test_new_hire_wait_is_judged_on_the_start_date(store):
    # E-1004 (hired 2026-10-05) can plan PTO that starts after 2027-01-03.
    assert hits(pto(store, "E-1004", 0.5, "2027-01-11"))["new_hire_wait"] == "pass"
    assert pto(store, "E-1002", None, None).missing_fields == ["days", "start_date"]


@pytest.mark.parametrize(("eid", "days", "state", "country", "outcome", "approvals"), [
    # Demo 1: Mexico City for 6 weeks needs tax and immigration review on top of the rest.
    ("E-1001", 42, None, "Mexico", "needs_review",
     ["Manager approval", "HR review", "Security review", "Tax review", "Immigration review"]),
    ("E-1001", 10, None, "Mexico", "needs_review",
     ["Manager approval", "HR review", "Security review"]),
    ("E-1001", 120, None, "Portugal", "not_allowed", None),     # >90 days generally declined
    ("E-1002", 10, "CO", None, "allowed", []),                  # domestic ≤14, check the map
    ("E-1002", 20, "CO", "United States", "needs_review", ["Manager approval", "Compliance review"]),
    ("E-1005", 10, "CO", None, "needs_review", ["Manager approval", "Compliance review"]),
    ("E-1001", 30, "MA", None, "allowed", []),                  # home state
    ("E-1003", 5, "CO", None, "not_allowed", None),             # contractor
    ("E-1004", 5, "CO", None, "not_allowed", None),             # security training incomplete
    ("E-1001", None, None, None, "needs_info", []),
])
def test_remote_rules(store, eid, days, state, country, outcome, approvals):
    decision = remote(store, eid, days, state, country)
    assert decision.outcome == outcome
    if approvals is not None:
        assert decision.required_approvals == approvals


def test_remote_blockers_name_the_rule(store):
    assert hits(remote(store, "E-1004", 5, "CO"))["security_training"] == "fail"
    assert hits(remote(store, "E-1005", 10, "CO"))["restricted_data"] == "review"
    short = remote(store, "E-1002", 20, "CO", start="2026-10-26")  # 2 business days' notice
    assert hits(short)["notice"] == "fail" and short.outcome == "not_allowed"


@pytest.mark.parametrize(("eid", "category", "amount", "outcome", "approvals"), [
    ("E-1007", "chair", 450, "not_allowed", None),                      # over $300
    ("E-1007", "chair", 280, "allowed_with_approval", ["Manager approval"]),
    ("E-1001", "laptop", 900, "not_allowed", None),                     # IT issues laptops
    ("E-1001", "lodging_high_cost", 340, "allowed_with_approval", ["Manager approval"]),
    ("E-1001", "lodging", 340, "not_allowed", None),
    ("E-1001", "other", 650, "allowed_with_approval", ["Manager approval", "Budget owner approval"]),
    ("E-1008", "internet", 40, "not_allowed", None),                    # not remote-eligible
    ("E-1001", "meals", None, "needs_info", []),
])
def test_expense_rules(store, eid, category, amount, outcome, approvals):
    decision = rules.check_expense(store.employee(eid), category, amount)
    assert decision.outcome == outcome
    if approvals is not None:
        assert decision.required_approvals == approvals


def test_business_days_until():
    monday = date(2026, 10, 26)
    assert rules.business_days_until(monday, monday + timedelta(days=7)) == 5
    assert rules.business_days_until(TODAY, date(2026, 11, 2)) == 7
    assert rules.business_days_until(TODAY, TODAY - timedelta(days=3)) == 0


def test_every_policy_ref_names_a_real_section():
    sections = {f"{d.doc_id}#{s.heading}" for d in load_documents(POLICY_DIR) for s in d.sections}
    assert set(rules.POLICY_REFS) <= sections, set(rules.POLICY_REFS) - sections


def test_data_store_lookups(store):
    assert store.employee("e-1001")["name"] == "Ava Patel"  # ids are case-insensitive
    assert store.recipient("PEOPLE-OPS")["email"] == "people.ops@example.com"
    assert store.recipient("M-42")["name"] == "Jordan Rivera"
    with pytest.raises(NotFound, match="E-9999"):
        store.employee("E-9999")
    with pytest.raises(NotFound):
        store.pto("E-9999")


def test_confirmation_tokens_are_single_use_bound_and_expiring():
    clock = [datetime(2026, 10, 22, 9, 0)]
    store = HRDataStore(MOCK_DATA_DIR, now=lambda: clock[0])
    payload = {"employee_id": "E-1001", "subject": "Remote work in Mexico"}

    token = store.propose("ticket", payload).token
    with pytest.raises(ValueError, match="does not match"):
        store.confirm(token, "ticket", {**payload, "subject": "Something else"})
    store.confirm(token, "ticket", payload)
    with pytest.raises(ValueError, match="already used"):
        store.confirm(token, "ticket", payload)

    late = store.propose("ticket", payload).token
    clock[0] += timedelta(minutes=11)
    with pytest.raises(ValueError, match="expired"):
        store.confirm(late, "ticket", payload)
    assert store.add_ticket(payload)["ticket_id"] == "HR-0003"  # after the 2 seed tickets
