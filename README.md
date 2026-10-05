# HR Policy Agent

A small, deployable HR policy assistant built as a FastAPI application. The project combines a synthetic policy corpus, lightweight retrieval, structured employee data, and an MCP-style tool layer for a realistic HR support workflow.

## Features
- FastAPI chat API with `/chat`, `/health`, `/evaluate`, and `/demo-tasks` endpoints
- Synthetic policy corpus stored in Markdown documents
- Lightweight heading-aware retrieval over policy snippets
- MCP-style tool layer for policy search, employee lookup, PTO, benefits, and mock HR actions
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
The repository includes a GitHub Actions workflow that installs dependencies and runs the pytest suite on push and pull request.

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

## Evaluation ideas
- Groundedness and citation checks for policy questions
- Multi-document retrieval for remote work and PTO scenarios
- Tool selection accuracy for HR workflows
- Safety checks for out-of-scope or ambiguous questions
