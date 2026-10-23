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
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or None
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Retrieval
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "gemini")
INDEX_DIR = _path("INDEX_DIR", "app/data/index")
VECTOR_TOP_K = int(os.getenv("VECTOR_TOP_K", "4"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.30"))

# MCP transport: "stdio" launches hr_mcp.server as a subprocess; "http" connects to MCP_SERVER_URL.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL") or None

# Agent
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "6"))
SEED = int(os.getenv("SEED", "42"))

DATA_DIR = BASE_DIR / "app" / "data"
POLICY_DIR = DATA_DIR / "policies"
MOCK_DATA_DIR = _path("MOCK_DATA_DIR", "mock_data")
# Legacy single-file data used by app/rag.py until P1/P2 move it onto MOCK_DATA_DIR.
EMPLOYEE_FILE = DATA_DIR / "employee_data.json"
