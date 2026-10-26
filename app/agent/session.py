"""In-memory chat sessions: recent turns, the acting employee, and actions awaiting confirmation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_TURNS = 6


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    employee_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    # token -> the exact tool arguments that were proposed; only the user's confirm uses them
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)

    def remember(self, user: str, assistant: str) -> None:
        self.history += [{"role": "user", "content": user},
                         {"role": "assistant", "content": assistant}]
        self.history = self.history[-2 * MAX_TURNS:]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str | None = None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = Session(session_id=session_id) if session_id else Session()
        self._sessions[session.session_id] = session
        return session
