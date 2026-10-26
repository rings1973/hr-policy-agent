"""Operational trace of one agent turn: which tools ran, with what arguments, how long they took.

Only facts that can be observed (no model chain-of-thought). Written to logs/trace.jsonl and
returned to the UI as `tool_trace`.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app import config

TRACE_FILE = config.BASE_DIR / "logs" / "trace.jsonl"
StepType = Literal["guardrail", "llm", "tool_call", "retrieval"]


@dataclass
class TraceStep:
    step: int
    type: StepType
    name: str
    ok: bool = True
    latency_ms: int = 0
    arguments: dict[str, Any] | None = None
    result_summary: str = ""


@dataclass
class Trace:
    steps: list[TraceStep] = field(default_factory=list)

    def add(self, type: StepType, name: str, **fields: Any) -> TraceStep:
        step = TraceStep(step=len(self.steps) + 1, type=type, name=name, **fields)
        self.steps.append(step)
        return step

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self.steps]

    def write(self, session_id: str, path: Path = TRACE_FILE) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "session_id": session_id,
                                     "steps": self.to_list()}) + "\n")
        except OSError:
            pass  # tracing must never break a reply (e.g. read-only filesystem)


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
