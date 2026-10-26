"""Deterministic policy checks for PTO, remote work and expenses.

Each check is a pure function of (employee record, request, today) that returns a Decision listing
every rule it applied, with a `policy_ref` of the form "doc_id#Section Heading" pointing at the
policy text the rule encodes. The LLM explains a Decision; it does not make one. The thresholds
mirror the synthetic policies in app/data/policies/ and must change together with them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

Outcome = Literal["allowed", "allowed_with_approval", "needs_review", "needs_info", "not_allowed"]
# pass: rule satisfied · fail: rule blocks the request · review: a reviewer must decide ·
# action_required: something the employee must do or provide · info: context only
Result = Literal["pass", "fail", "review", "action_required", "info"]

PTO_SCOPE = "pto_policy#Purpose and Scope"
PTO_ENTITLEMENT = "pto_policy#Annual PTO Entitlement"
PTO_NOTICE = "pto_policy#Notice and Approval Requirements"
PTO_COVERAGE = "pto_policy#Manager Review and Coverage"
PTO_ACCRUAL = "pto_policy#Balance, Accrual, and Corrections"
REMOTE_ELIGIBILITY = "remote_work_policy#Eligibility"
REMOTE_RULE = "remote_work_policy#Decision Rule"
REMOTE_DOCUMENTATION = "remote_work_policy#Documentation"
REMOTE_DOMESTIC = "remote_work_policy#Short-Term Domestic Work"
REMOTE_SECURITY = "remote_work_policy#Security and Equipment Requirements"
EXPENSE_LIMITS = "expense_policy#Reimbursement Limits"
EXPENSE_APPROVAL = "expense_policy#Approval Before Purchase"
EQUIPMENT_ISSUANCE = "equipment_policy#Issuance and Inventory"

POLICY_REFS = (
    PTO_SCOPE, PTO_ENTITLEMENT, PTO_NOTICE, PTO_COVERAGE, PTO_ACCRUAL, REMOTE_ELIGIBILITY,
    REMOTE_RULE,
    REMOTE_DOCUMENTATION, REMOTE_DOMESTIC, REMOTE_SECURITY, EXPENSE_LIMITS, EXPENSE_APPROVAL,
    EQUIPMENT_ISSUANCE,
)

MANAGER = "Manager approval"
COMPLIANCE = "Compliance review"
HR = "HR review"
SECURITY = "Security review"
TAX = "Tax review"
IMMIGRATION = "Immigration review"
BUDGET_OWNER = "Budget owner approval"
PEOPLE_OPS = "People Operations"

NOT_COVERED = {"contract": "Contractors", "intern": "Interns"}
NEW_HIRE_WAIT_DAYS = 90
PTO_NOTICE_DAYS, PTO_LONG_NOTICE_DAYS, PTO_LONG_REQUEST_DAYS = 5, 10, 3
# Full-time annual PTO by full years of service, highest threshold first.
PTO_TIERS = ((5, 25), (2, 20), (0, 15))
PTO_CARRYOVER_MAX = 5
CARRYOVER_EXPIRES = (3, 31)  # month, day
PAY_PERIODS_PER_YEAR = 24  # the policy says "each pay period" without a length: semi-monthly
REMOTE_NOTICE_DAYS = 10
DOMESTIC_DAYS, INTERNATIONAL_TAX_DAYS, INTERNATIONAL_MAX_DAYS = 14, 30, 90

ExpenseCategory = Literal[
    "chair", "desk", "peripherals", "laptop", "internet", "meals", "lodging",
    "lodging_high_cost", "other",
]
# category -> (limit in USD, what the limit is per)
EXPENSE_LIMITS_USD: dict[str, tuple[float, str]] = {
    "chair": (300, "item, once every 3 years"),
    "desk": (300, "item, once every 3 years"),
    "peripherals": (250, "calendar year in total"),
    "internet": (50, "month"),
    "meals": (75, "traveler per day, including tax and tip"),
    "lodging": (250, "night in a standard market"),
    "lodging_high_cost": (350, "night in a designated high-cost city"),
}
DUAL_APPROVAL_OVER_USD = 500

_US = {"US", "USA", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"}


@dataclass
class RuleHit:
    rule: str
    result: Result
    detail: str
    policy_ref: str


@dataclass
class Decision:
    request_type: str
    employee_id: str
    outcome: Outcome = "allowed"
    rule_hits: list[RuleHit] = field(default_factory=list)
    required_approvals: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    def hit(self, rule: str, result: Result, detail: str, policy_ref: str,
            approvals: tuple[str, ...] = ()) -> None:
        self.rule_hits.append(RuleHit(rule, result, detail, policy_ref))
        for approval in approvals:
            if approval not in self.required_approvals:
                self.required_approvals.append(approval)

    def finish(self) -> Decision:
        """Outcome precedence: a failed rule beats missing input, which beats a pending review."""
        results = {h.result for h in self.rule_hits}
        if "fail" in results:
            self.outcome = "not_allowed"
        elif self.missing_fields:
            self.outcome = "needs_info"
        elif "review" in results:
            self.outcome = "needs_review"
        elif self.required_approvals:
            self.outcome = "allowed_with_approval"
        else:
            self.outcome = "allowed"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def business_days_until(today: date, start: date) -> int:
    """Weekdays from today (inclusive) up to the start date (exclusive): the working days of
    notice given. Company holidays are not subtracted because the calendar is not in the data."""
    days, current = 0, today
    while current < start:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def last_business_day(start: date, days: float) -> date:
    """Last weekday of a run of `days` business days starting on `start` (partial days round up)."""
    remaining, current = max(1, int(-(-days // 1))), start
    while current.weekday() >= 5:
        current += timedelta(days=1)
    while True:
        if current.weekday() < 5:
            remaining -= 1
            if remaining == 0:
                return current
        current += timedelta(days=1)


def full_years(start: date, on: date) -> int:
    return on.year - start.year - ((on.month, on.day) < (start.month, start.day))


def tier_days(hire: date, on: date) -> int:
    years = full_years(hire, on)
    return next(days for min_years, days in PTO_TIERS if years >= min_years)


def is_pay_date(day: date) -> bool:
    """Semi-monthly pay dates: the 15th and the last day of each month."""
    return day.day == 15 or (day + timedelta(days=1)).day == 1


def project_pto(employee: dict[str, Any], balance: dict[str, Any], as_of: date,
                target: date) -> dict[str, Any]:
    """Estimate the PTO balance on `target`, assuming no PTO is used or requested after `as_of`.

    The current `available` balance is the starting point. Each pay period adds the tenure tier
    (scaled for part-time) / 24; on 31 Dec at most 5 days carry over and the rest is forfeited;
    carried-over days not used by 31 Mar expire (with no usage assumed, all of them do).
    """
    out: dict[str, Any] = {"employee_id": employee["employee_id"], "as_of": as_of.isoformat(),
                           "target_date": target.isoformat(), "unit": "days",
                           "estimate": True, "policy_ref": PTO_ENTITLEMENT}
    group = NOT_COVERED.get(employee["employment_type"])
    if group:
        return {**out, "accrues": False, "projected_available": balance["available"],
                "detail": f"{group} do not accrue PTO under the policy; their agreement governs "
                          "time off.", "policy_ref": PTO_SCOPE}
    if target <= as_of:
        return {**out, "accrues": True, "projected_available": balance["available"],
                "detail": "Target date is not after the balance date; this is the current "
                          "balance.", "events": []}

    hire = date.fromisoformat(employee["hire_date"])
    # Part-time entitlements are prorated: keep the record's ratio to the full-time tier.
    fte = balance["annual_entitlement"] / tier_days(hire, as_of)
    bal, carried, accrued, forfeited, expired = balance["available"], 0.0, 0.0, 0.0, 0.0
    events: list[str] = []
    rate_year = tier_days(hire, as_of)
    day = as_of
    while day < target:
        day += timedelta(days=1)
        if (day.month, day.day) == (1, 1):  # year end has passed
            carried = min(bal, PTO_CARRYOVER_MAX)
            if bal > carried:
                forfeited += bal - carried
                events.append(f"{day.year - 1}-12-31: {bal - carried:.2f} days over the "
                              f"{PTO_CARRYOVER_MAX}-day carryover cap are forfeited; "
                              f"{carried:.2f} carry over.")
            bal = carried
        if day == date(day.year, *CARRYOVER_EXPIRES) + timedelta(days=1) and carried:
            expired, bal = expired + carried, bal - carried
            events.append(f"{day.year}-03-31: {carried:.2f} carried-over days expire unless used "
                          "by then.")
            carried = 0.0
        if is_pay_date(day):
            tier = tier_days(hire, day)
            if tier != rate_year:
                years = full_years(hire, day)
                anniversary = hire.replace(year=hire.year + years)
                events.append(f"{anniversary.isoformat()}: {years} full years of service; "
                              f"entitlement rises to {tier * fte:g} days/year from the "
                              f"{day.isoformat()} pay date.")
                rate_year = tier
            step = tier * fte / PAY_PERIODS_PER_YEAR
            bal, accrued = bal + step, accrued + step

    eligible_from = hire + timedelta(days=NEW_HIRE_WAIT_DAYS)
    summary = f"About {bal:.2f} days on {target.isoformat()} if no PTO is used before then."
    if forfeited:
        summary += (f" {forfeited:.2f} days would be lost to the {PTO_CARRYOVER_MAX}-day year-end "
                    "carryover cap: use them before 31 December to keep them.")
    if expired:
        summary += f" {expired:.2f} carried-over days expire unless used by 31 March."
    return {**out, "accrues": True, "summary": summary,
            "current_available": balance["available"],
            "accrued": round(accrued, 2),
            "forfeited_over_cap": round(forfeited, 2),
            "expired_carryover": round(expired, 2),
            "projected_available": round(bal, 2),
            "usable_on_target": target >= eligible_from,
            "events": events,
            "assumptions": [
                "No PTO is used or requested after the balance date.",
                (f"Accrual is paid semi-monthly ({PAY_PERIODS_PER_YEAR} pay periods a year) on "
                 "the 15th and last day of the month; the policy does not state the pay period."),
                "Unused carried-over days expire on 31 March.",
                "The HR system is the authoritative balance; this is an estimate."]}


def _not_covered(decision: Decision, employee: dict[str, Any], policy_ref: str, what: str) -> bool:
    group = NOT_COVERED.get(employee["employment_type"])
    if group:
        decision.hit("employment_type", "fail",
                     f"{group} are not covered by the {what} policy; their agreement governs this. "
                     "Contact People Operations and the contract owner.", policy_ref)
    return bool(group)


def check_pto(employee: dict[str, Any], balance: dict[str, Any], days: float | None,
              start_date: date | None, today: date) -> Decision:
    d = Decision("pto", employee["employee_id"])
    if _not_covered(d, employee, PTO_SCOPE, "PTO"):
        return d.finish()
    d.hit("manager_approval", "info", "Planned PTO always needs manager approval in the HR system.",
          PTO_NOTICE, approvals=(MANAGER,))

    eligible_from = date.fromisoformat(employee["hire_date"]) + timedelta(days=NEW_HIRE_WAIT_DAYS)
    first_day = start_date or today
    if first_day < eligible_from:
        d.hit("new_hire_wait", "fail",
              f"New employees may use PTO after {NEW_HIRE_WAIT_DAYS} days of employment; this "
              f"employee becomes eligible on {eligible_from.isoformat()}. Emergency absences can "
              "be approved by People Operations.", PTO_ENTITLEMENT)
    else:
        d.hit("new_hire_wait", "pass", f"Past the {NEW_HIRE_WAIT_DAYS}-day new-hire wait.",
              PTO_ENTITLEMENT)

    if days is None:
        d.missing_fields.append("days")
    elif days > balance["available"]:
        d.hit("balance", "fail",
              f"Requested {days:g} days but only {balance['available']:g} are available. Requests "
              "over the balance must be discussed with People Operations, who may approve unpaid "
              "time off in limited cases.", PTO_NOTICE, approvals=(PEOPLE_OPS,))
    else:
        d.hit("balance", "pass",
              f"Requested {days:g} days; {balance['available']:g} available.", PTO_NOTICE)

    if start_date is None:
        d.missing_fields.append("start_date")
    elif days is not None:
        required = PTO_LONG_NOTICE_DAYS if days > PTO_LONG_REQUEST_DAYS else PTO_NOTICE_DAYS
        given = business_days_until(today, start_date)
        if given < required:
            d.hit("notice", "fail",
                  f"{days:g} days needs at least {required} business days' notice; starting "
                  f"{start_date.isoformat()} gives {given}. For an unexpected absence, use the "
                  "emergency absence process instead.", PTO_NOTICE)
        else:
            d.hit("notice", "pass", f"{given} business days' notice (at least {required} needed).",
                  PTO_NOTICE)

    if start_date is not None and days is not None and days >= 1:
        # Give the model the date range instead of letting it do calendar arithmetic.
        end = last_business_day(start_date, days)
        d.hit("dates", "info", f"{days:g} business days from {start_date.isoformat()} "
              f"({start_date:%A}) end on {end.isoformat()} ({end:%A}), not counting holidays.",
              PTO_NOTICE)

    if days is not None and days > PTO_LONG_REQUEST_DAYS:
        d.hit("coverage_plan", "action_required",
              f"More than {PTO_LONG_REQUEST_DAYS} consecutive days needs a coverage plan agreed "
              "with the manager.", PTO_COVERAGE)
    return d.finish()


def _country(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    upper = value.strip().upper()
    return "US" if upper in _US else upper


def check_remote(employee: dict[str, Any], days: int | None, destination_state: str | None,
                 destination_country: str | None, start_date: date | None,
                 today: date) -> Decision:
    d = Decision("remote_work", employee["employee_id"])
    if _not_covered(d, employee, REMOTE_ELIGIBILITY, "remote work"):
        return d.finish()
    if not employee["remote_work_eligible"]:
        d.hit("remote_eligible", "fail", "The employee profile is not marked remote-work eligible.",
              REMOTE_ELIGIBILITY)
    if not employee["security_training_complete"]:
        d.hit("security_training", "fail",
              "Annual security training must be complete before remote access is granted.",
              REMOTE_SECURITY)

    home_country = _country(employee["home_country"]) or "US"
    country = _country(destination_country) or (home_country if destination_state else None)
    if country is None:
        d.missing_fields.append("destination_state or destination_country")
    if days is None:
        d.missing_fields.append("days")
    if country is None or days is None:
        return d.finish()

    if country != home_country:
        d.hit("international", "review",
              "Any international work needs manager approval plus HR and security review before "
              "work begins.", REMOTE_RULE, approvals=(MANAGER, HR, SECURITY))
        if days > INTERNATIONAL_MAX_DAYS:
            d.hit("international_duration", "fail",
                  f"International requests longer than {INTERNATIONAL_MAX_DAYS} days are generally "
                  "declined; an exception needs every required owner's documented approval.",
                  REMOTE_RULE)
        elif days > INTERNATIONAL_TAX_DAYS:
            d.hit("international_duration", "review",
                  f"More than {INTERNATIONAL_TAX_DAYS} days abroad also needs tax and immigration "
                  "review.", REMOTE_RULE, approvals=(TAX, IMMIGRATION))
    else:
        state = (destination_state or "").strip().upper()
        if not state or state == employee["home_state"].upper():
            d.hit("location", "pass",
                  "Work from the home location: standard remote work (up to 2 days per week).",
                  REMOTE_ELIGIBILITY)
            return d.finish()
        if days > DOMESTIC_DAYS:
            d.hit("domestic_duration", "review",
                  f"More than {DOMESTIC_DAYS} calendar days outside the home state needs manager "
                  "approval and a compliance review before work begins.", REMOTE_RULE,
                  approvals=(MANAGER, COMPLIANCE))
        else:
            d.hit("domestic_duration", "action_required",
                  f"Up to {DOMESTIC_DAYS} days in another state is allowed with manager awareness "
                  f"if {state} is on the approved remote work map; confirm that first.", REMOTE_RULE)
            if employee["handles_restricted_data"]:
                d.hit("restricted_data", "review",
                      "Shorter stays may still need approval when the employee handles restricted "
                      "information.", REMOTE_DOMESTIC, approvals=(MANAGER, COMPLIANCE))

    if start_date is None:
        d.hit("notice", "info", f"Submit the request at least {REMOTE_NOTICE_DAYS} business days "
              "before the first remote workday away from home.", REMOTE_DOCUMENTATION)
    else:
        given = business_days_until(today, start_date)
        result: Result = "pass" if given >= REMOTE_NOTICE_DAYS else "fail"
        d.hit("notice", result, f"Requests need {REMOTE_NOTICE_DAYS} business days' notice; "
              f"starting {start_date.isoformat()} gives {given}.", REMOTE_DOCUMENTATION)
        # Calendar days, inclusive: the model wrote Feb 22 for 42 days from Jan 11 (it's Feb 21).
        end = start_date + timedelta(days=days - 1)
        d.hit("dates", "info", f"{days} calendar days from {start_date.isoformat()} "
              f"({start_date:%A}) end on {end.isoformat()} ({end:%A}).", REMOTE_RULE)
    return d.finish()


def check_expense(employee: dict[str, Any], category: str | None, amount: float | None) -> Decision:
    d = Decision("expense", employee["employee_id"])
    if category is None:
        d.missing_fields.append("expense_category")
    if amount is None:
        d.missing_fields.append("amount")
    if category is None or amount is None:
        return d.finish()

    if category == "laptop":
        d.hit("laptop", "fail",
              "Laptops and other computing devices are not reimbursable; request one from IT as "
              "company-managed equipment.", EXPENSE_LIMITS)
        d.hit("laptop_request", "info", "IT issues a managed laptop through the service desk.",
              EQUIPMENT_ISSUANCE)
        return d.finish()

    if category in EXPENSE_LIMITS_USD:
        limit, per = EXPENSE_LIMITS_USD[category]
        if amount > limit:
            d.hit("category_limit", "fail",
                  f"${amount:,.2f} exceeds the {category.replace('_', ' ')} limit of ${limit:,.0f} "
                  f"per {per}, unless a documented exception is approved in advance.",
                  EXPENSE_LIMITS)
        else:
            d.hit("category_limit", "pass",
                  f"${amount:,.2f} is within the ${limit:,.0f} per {per} limit.", EXPENSE_LIMITS)
    if category == "internet" and not employee["remote_work_eligible"]:
        d.hit("internet_eligibility", "fail",
              "Home internet is reimbursed only for employees approved for regular remote work.",
              EXPENSE_LIMITS)

    if amount > DUAL_APPROVAL_OVER_USD:
        d.hit("dual_approval", "info", f"Any single expense over ${DUAL_APPROVAL_OVER_USD} needs "
              "pre-approval from both the manager and the budget owner.", EXPENSE_LIMITS,
              approvals=(MANAGER, BUDGET_OWNER))
    else:
        d.hit("pre_approval", "info", "Get manager approval before committing company funds.",
              EXPENSE_APPROVAL, approvals=(MANAGER,))
    d.hit("receipt", "action_required", "Keep an itemized receipt and submit within 30 days; "
          "expenses submitted after 90 days are not reimbursed.", EXPENSE_LIMITS)
    return d.finish()
