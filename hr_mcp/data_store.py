"""Read-only access to the synthetic records in mock_data/, plus in-memory mock tickets.

Nothing here knows about MCP: lookups raise NotFound / ValueError and the server turns those into
tool errors. New tickets live only in this process and are never sent anywhere.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PENDING_TTL = timedelta(minutes=10)
# draft_hr_email can address People Operations as well as an employee or manager id.
PEOPLE_OPS = {"id": "PEOPLE-OPS", "name": "People Operations", "email": "people.ops@example.com"}


class NotFound(LookupError):
    """An employee, manager or record id that is not in the mock data."""


@dataclass
class PendingAction:
    token: str
    kind: str
    payload: dict[str, Any]
    expires_at: datetime


@dataclass
class HRDataStore:
    data_dir: Path
    now: Callable[[], datetime] = datetime.now
    tickets: list[dict[str, Any]] = field(init=False)
    pending: dict[str, PendingAction] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self._employees = self._index("employees.json", "employees", "employee_id")
        self._managers = self._index("managers.json", "managers", "manager_id")
        self._pto = self._index("pto_balances.json", "balances", "employee_id")
        self._benefits = self._index("benefits.json", "enrollments", "employee_id")
        self.as_of = self._load("employees.json").get("as_of")
        self.tickets = list(self._load("tickets.json")["tickets"])

    def _load(self, name: str) -> dict[str, Any]:
        return json.loads((self.data_dir / name).read_text(encoding="utf-8"))

    def _index(self, name: str, key: str, id_field: str) -> dict[str, dict[str, Any]]:
        return {row[id_field]: row for row in self._load(name)[key]}

    @staticmethod
    def _get(table: dict[str, dict[str, Any]], record_id: str, label: str) -> dict[str, Any]:
        record = table.get(record_id.strip().upper())
        if record is None:
            known = ", ".join(sorted(table))
            raise NotFound(f"Unknown {label} id {record_id!r}. Known ids: {known}.")
        return dict(record)

    def employee(self, employee_id: str) -> dict[str, Any]:
        return self._get(self._employees, employee_id, "employee")

    def manager(self, manager_id: str) -> dict[str, Any]:
        return self._get(self._managers, manager_id, "manager")

    def pto(self, employee_id: str) -> dict[str, Any]:
        self.employee(employee_id)  # a clear "unknown employee" error beats "no PTO record"
        return self._get(self._pto, employee_id, "PTO record for employee")

    def benefits(self, employee_id: str) -> dict[str, Any]:
        self.employee(employee_id)
        return self._get(self._benefits, employee_id, "benefits record for employee")

    def recipient(self, recipient_id: str) -> dict[str, Any]:
        """Resolve an email recipient: an employee id, a manager id, or PEOPLE-OPS."""
        rid = recipient_id.strip().upper()
        if rid == PEOPLE_OPS["id"]:
            return dict(PEOPLE_OPS)
        if rid in self._managers:
            m = self._managers[rid]
            return {"id": rid, "name": m["name"], "email": m["email"]}
        if rid in self._employees:
            e = self._employees[rid]
            return {"id": rid, "name": e["name"], "email": e["email"]}
        raise NotFound(
            f"Unknown recipient {recipient_id!r}. Use an employee id, a manager id or PEOPLE-OPS."
        )

    # Two-phase mock actions -------------------------------------------------------------

    def propose(self, kind: str, payload: dict[str, Any]) -> PendingAction:
        """Hold an action until the user confirms it. The token is single-use and expires."""
        self._expire()
        action = PendingAction(
            token=secrets.token_urlsafe(16), kind=kind, payload=dict(payload),
            expires_at=self.now() + PENDING_TTL,
        )
        self.pending[action.token] = action
        return action

    def confirm(self, token: str, kind: str, payload: dict[str, Any]) -> PendingAction:
        """Consume a token. It must exist, be unexpired, and match the proposed payload exactly,
        so a confirmed preview cannot be swapped for a different action."""
        self._expire()
        action = self.pending.get(token)
        if action is None or action.kind != kind:
            raise ValueError("Confirmation token is invalid, expired, or already used.")
        if action.payload != payload:
            raise ValueError("Confirmation token does not match this request; propose it again.")
        del self.pending[token]
        return action

    def _expire(self) -> None:
        now = self.now()
        for token in [t for t, a in self.pending.items() if a.expires_at <= now]:
            del self.pending[token]

    def add_ticket(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticket = {
            "ticket_id": f"HR-{len(self.tickets) + 1:04d}",
            **payload,
            "status": "open",
            "created": self.now().date().isoformat(),
            "mock": True,
        }
        self.tickets.append(ticket)
        return ticket
