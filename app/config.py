from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _path(name: str, default: str) -> Path:
    """Resolve a path setting relative to the repo root unless it is absolute."""
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else BASE_DIR / value


APP_NAME = os.getenv("APP_NAME", "hr-policy-agent")
APP_ENV = os.getenv("APP_ENV", "development")

# LLM providers, tried in order. An empty key disables that provider.
LLM_PROVIDERS = [p.strip() for p in os.getenv("LLM_PROVIDERS", "groq,gemini").split(",") if p.strip()]
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or None
# Each Groq model has its own 8k tokens/minute free-tier limit, so fallbacks add headroom.
# qwen made parallel tool calls and never returned the empty replies seen from gpt-oss.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b").split(",") if m.strip()]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or None
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# low | medium | high, or empty for the provider default. Hidden reasoning counts toward
# Groq's per-minute token limit, but "low" was seen to end turns with no output (2026-10-26).
GPT_OSS_REASONING_EFFORT = os.getenv("GPT_OSS_REASONING_EFFORT", "medium") or None

# Retrieval
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "gemini")
INDEX_DIR = _path("INDEX_DIR", "app/data/index")
VECTOR_TOP_K = int(os.getenv("VECTOR_TOP_K", "4"))
# Optional override of the per-embedder weak-evidence threshold stored in manifest.json.
MIN_SCORE = float(os.environ["MIN_SCORE"]) if os.getenv("MIN_SCORE") else None

# MCP transport: "stdio" launches hr_mcp.server as a subprocess; "http" connects to MCP_SERVER_URL.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL") or None

# Agent
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "8"))
SEED = int(os.getenv("SEED", "42"))
# "Today" for date rules (90-day wait, notice periods). Empty means the real date; pin it
# (YYYY-MM-DD) so evaluation runs give the same decisions on any day.
REFERENCE_DATE = os.getenv("REFERENCE_DATE") or None

DATA_DIR = BASE_DIR / "app" / "data"
POLICY_DIR = DATA_DIR / "policies"
MOCK_DATA_DIR = _path("MOCK_DATA_DIR", "mock_data")
# Legacy single-file data used by app/legacy_rag.py until P1/P2 move it onto MOCK_DATA_DIR.
EMPLOYEE_FILE = DATA_DIR / "employee_data.json"
