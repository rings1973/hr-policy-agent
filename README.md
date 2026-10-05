# HR Policy Agent

A small, deployable HR policy assistant built as a FastAPI application. The project combines a synthetic policy corpus, local sparse-vector retrieval, structured employee data, and an MCP-compatible tool layer for a realistic HR support workflow.

## Features
- FastAPI chat API with `/chat`, `/health`, `/evaluate`, and `/demo-tasks` endpoints
- Ten synthetic policy sources in Markdown and TXT, approximately 46 standard 250-word pages across PTO, holidays, remote work, expenses, data security, benefits, onboarding, equipment, leave, and workplace conduct
- Heading-aware ingestion with local TF-IDF sparse vectors persisted alongside chunk metadata in SQLite (a lightweight baseline, not a pretrained semantic embedding model)
- MCP-compatible stateless HTTP endpoint at `/mcp` for tool discovery and calls, plus policy search, employee lookup, PTO, benefits, and mock HR actions
- Agent orchestration for remote-work and PTO workflows
- Smoke tests and CI workflow for startup and tool validation
- Render-ready single-service deployment configuration for free-tier hosting

## Project structure
- `app/main.py` – FastAPI app and endpoints
- `app/agent.py` – orchestration for tool selection and answer synthesis
- `app/mcp_server.py` – MCP-style tool definitions and execution layer
- `app/rag.py` – markdown ingestion and retrieval logic
- `app/data/` – synthetic employee data and policy corpus
- `tests/` – pytest smoke and MCP validation tests

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://localhost:8000/` to test the chat UI.

## Example tasks
1. Remote work eligibility: "Can Ava work remotely from another state for six weeks?"
2. PTO guidance: "What is the current PTO balance and what steps are required for a planned PTO request?"

## Architecture summary

```text
Browser / UI
   |
   v
FastAPI app (/chat, /health)
   |
   +--> HR Policy Agent
   |      +--> MCP Tool Server
   |      |      +--> Policy RAG index
   |      |      +--> Employee records (JSON)
   |      |      +--> Mock ticket/email operations
   |      |
   |      +--> Final answer + citations + tool trace
```

## CI and validation
The repository includes a GitHub Actions workflow that installs dependencies and runs the pytest suite on Python 3.13 for push and pull request. The TF-IDF vector index is rebuilt from committed policy files at application startup; no model download or paid API is required.

## Deployment notes
This project is designed for a single-service free-tier deployment. A Render or Railway service can run the FastAPI app and local MCP-style tool layer together without a paid database.

### Render deployment
Use the included `render.yaml` or a single web service with the following settings:
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- Python version: `3.13`

### Demo tasks for grading
Use the `/demo-tasks` endpoint or the UI to reproduce the required tasks:
1. Remote work eligibility: "Can Ava work remotely from another state for six weeks?"
2. PTO request guidance: "What is Ava's current PTO balance and what steps are required to request time off?"

## Security notes
- Secret keys should live in `.env` and are excluded from Git.
- Synthetic employee data is intentionally mock and non-production.
- The app avoids carrying out irreversible actions without explicit confirmation.

## Evaluation
Run `python -m app.evaluation` or open `/evaluate` to execute the 22-case benchmark. It reports keyword-based groundedness, source-section citation validity, expected-tool overlap, workflow completion, safety pass rate, observed p50/p95 latency, and retrieval keyword-coverage comparisons at top-k 1, 3, and 5. The local snapshot and its limitations are recorded in [docs/requirements-traceability.md](docs/requirements-traceability.md). These are lightweight proxy metrics, not human-judged quality scores or cold-start measurements.

## Requirements status
See [docs/requirements-traceability.md](docs/requirements-traceability.md) for the end-to-end flow and a checked/partial/open checklist against the assignment. The deployed shareable URL, target corpus length, stronger semantic embeddings, and formal ablation interpretation still require follow-up; the checklist makes those limitations explicit.
