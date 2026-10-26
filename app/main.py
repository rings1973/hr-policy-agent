"""Web app for the HR policy agent.

    uvicorn app.main:app --reload            http://127.0.0.1:8000

The lifespan starts one MCP server subprocess (hr_mcp.server over stdio) and builds the agent;
both live for the whole app. If startup fails the app still serves, with /health "degraded" and
/chat returning an error status, so the page can explain what is wrong.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config, demo_questions
from app.agent import AgentResult, HRAgent, LLMClient, MCPToolClient, SessionStore
from evaluation import report
from hr_mcp.data_store import HRDataStore

STATIC_DIR = config.BASE_DIR / "app" / "static"
RESULTS_DIR = config.BASE_DIR / "evaluation" / "results"
VERSION = "0.5.0"


def index_info() -> dict[str, Any]:
    """What the MCP server's index was built with, read from its manifest (the server falls back
    to tfidf the same way when the preferred index is missing)."""
    for name in dict.fromkeys([config.EMBEDDING_BACKEND, "tfidf"]):
        path = config.INDEX_DIR / name / "manifest.json"
        if path.exists():
            m = json.loads(path.read_text(encoding="utf-8"))
            return {"embedder": m["embedder"], "model": m["model"], "chunks": m["chunks"],
                    "documents": m["documents"], "built_at": m.get("built_at")}
    return {"error": f"no index under {config.INDEX_DIR}"}


@dataclass
class AppState:
    sessions: SessionStore = field(default_factory=SessionStore)
    tools: MCPToolClient | None = None
    agent: HRAgent | None = None
    llm: LLMClient | None = None
    startup_error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = AppState()
    try:
        tools = MCPToolClient()
        await tools.start()
        state.tools, state.llm = tools, LLMClient()
        state.agent = HRAgent(state.llm, tools)
    except Exception as exc:  # noqa: BLE001 - serve a degraded app rather than crash
        state.startup_error = f"{type(exc).__name__}: {exc}"
    app.state.hr = state
    try:
        yield
    finally:
        if state.tools is not None:
            await state.tools.aclose()


app = FastAPI(title="HR Policy Agent", version=VERSION, lifespan=lifespan)


def hr(request: Request) -> AppState:
    return request.app.state.hr


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    employee_id: str | None = None


class ConfirmRequest(BaseModel):
    session_id: str
    token: str
    approve: bool


def unavailable(state: AppState, session_id: str, employee_id: str | None) -> dict[str, Any]:
    return AgentResult(f"The assistant could not start: {state.startup_error}", "error",
                       session_id, employee_id).to_dict()


@app.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    state = hr(request)
    session = state.sessions.get(body.session_id)
    picked = (body.employee_id or "").strip().upper() or None
    if picked != session.employee_id:
        session.employee_id = picked  # the "Acting as" picker is the source of identity
    if state.agent is None:
        return unavailable(state, session.session_id, session.employee_id)
    return (await state.agent.run(body.message, session)).to_dict()


@app.post("/chat/confirm")
async def confirm(body: ConfirmRequest, request: Request) -> dict[str, Any]:
    state = hr(request)
    session = state.sessions.get(body.session_id)
    if state.agent is None:
        return unavailable(state, session.session_id, session.employee_id)
    return (await state.agent.confirm(session, body.token, body.approve)).to_dict()


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = hr(request)
    mcp: dict[str, Any] = {"connected": False, "transport": "stdio", "tool_count": 0}
    if state.tools is not None and state.tools.connected:
        start = time.perf_counter()
        try:
            mcp["tool_count"] = len(await state.tools.list_tools())
            mcp["connected"] = True
        except Exception as exc:  # noqa: BLE001
            mcp["error"] = str(exc)
        mcp["ping_ms"] = int((time.perf_counter() - start) * 1000)
    providers = [f"{p.name}/{p.model}" for p in state.llm.providers] if state.llm else []
    ok = mcp["connected"] and bool(providers)
    return {"status": "ok" if ok else "degraded", "version": VERSION, "mcp": mcp,
            "llm": {"providers_configured": providers}, "index": index_info(),
            **({"error": state.startup_error} if state.startup_error else {})}


@app.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    state = hr(request)
    if state.tools is None:
        return {"tools": []}
    return {"tools": [{"name": t.name, "description": (t.description or "").split("\n")[0]}
                      for t in await state.tools.list_tools()]}


@app.get("/employees")
def employees() -> dict[str, Any]:
    """Names and roles for the "Acting as" picker (synthetic records, no balances)."""
    store = HRDataStore(config.MOCK_DATA_DIR)
    rows = [store.employee(eid) for eid in store.employee_ids()]
    return {"employees": [{"employee_id": e["employee_id"], "name": e["name"], "role": e["role"],
                           "employment_type": e["employment_type"]} for e in rows]}


@app.get("/demo-tasks")
def demo_tasks() -> dict[str, Any]:
    return {"groups": demo_questions.as_dict()}


@app.get("/eval/latest")
def eval_latest() -> dict[str, Any]:
    """Headline numbers from the newest committed evaluation results (no per-case transcripts)."""
    return report.latest_summary(RESULTS_DIR)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
