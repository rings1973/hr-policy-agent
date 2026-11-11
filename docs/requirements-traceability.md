# Requirements traceability

Each requirement of the Quantic MSAIE Project 3 brief, mapped to where it is met and how it is checked.
Status: ✅ done and verified, 🚀 needs the live deployment (filled in `deployed.md`).

## 1. Environment and reproducibility

| Requirement | Evidence |
|---|---|
| Virtual environment | `.venv` (Python 3.13); setup in [README](../README.md#run-locally) ✅ |
| Dependencies listed | `requirements.txt` (pinned runtime), `requirements-dev.txt` (+ pytest, ruff), `pyproject.toml` ✅ |
| README: setup, local run, deployment, evaluation | [README.md](../README.md): Run locally, Tests and evaluation, CI/CD and deployment, Deploy your own copy ✅ |
| Fixed seeds / determinism | Deterministic chunk ids (`app/rag/chunker.py`), `SEED=42` passed to the LLM where supported (`app/agent/llm.py`), `REFERENCE_DATE` pins "today" for date rules (eval and CI use 2026-10-22), temperature 0 ✅ |
| Secrets from environment only | `app/config.py` reads all keys from env; `.env` git-ignored; Render keys are `sync: false` in `render.yaml` ✅ |

## 2. Corpus ingestion and indexing

| Requirement | Evidence |
|---|---|
| 5–20 files, 30–120 pages, HR topics | 12 documents, about 20k words (about 80 pages): PTO, holidays, remote work, expenses, data security, benefits, onboarding, equipment, leave, conduct; licenses in [SOURCES.md](../app/data/policies/SOURCES.md) ✅ |
| At least two formats | Markdown, TXT, PDF (NIST excerpt) and HTML (OPM fact sheet): `app/rag/loaders.py`; `tests/test_rag.py` ✅ |
| Justified chunking | Heading-aware sections; sections over 350 words split into windows with 60 words of overlap; disclaimer-only sections dropped (`app/rag/chunker.py`, rationale in [design-and-evaluation.md](../design-and-evaluation.md)) ✅ |
| Free embedding model | Gemini `gemini-embedding-001` (free tier), TF-IDF as the keyless baseline (`app/rag/embeddings.py`) ✅ |
| Vector store | FAISS `IndexFlatIP` + SQLite metadata + `manifest.json` (`app/rag/index.py`), built by `python -m app.rag.ingest` ✅ |
| Citation metadata | Each chunk stores doc id, title, section, page, source type and snippet ✅ |

## 3. RAG

| Requirement | Evidence |
|---|---|
| Top-k with filtering | `search_policy_documents(query, k, document_id, include_external)`, per-embedder `MIN_SCORE` marks weak evidence ✅ |
| Retrieved chunks and metadata injected into the prompt | Tool results carry chunk text and metadata into the model context (`app/agent/orchestrator.py`, `app/agent/prompts.py`) ✅ |
| Answers cite ids, sections and snippets | `final_answer.citations`, validated against chunks actually returned this turn (`app/agent/guardrails.py: validate_citations`) ✅ |
| Guardrails: out-of-corpus, unsupported claims, facts vs recommendations | `pre_route` (out-of-scope, legal, sensitive HR, emergency), "not covered" reply without evidence, separate `policy_facts` and `recommendations` fields; `tests/test_agent.py` ✅ |
| A multi-document question | 5 `multi_doc` cases in `evaluation/cases.yaml` ✅ |

## 4. Agentic system

| Requirement | Evidence |
|---|---|
| Orchestrator: intent, RAG vs tools, synthesis | `app/agent/orchestrator.py` (LLM tool loop, max 8 steps, finalize step) ✅ |
| At least two multi-step workflows | Remote work eligibility and PTO request with manager email (Demo 1 and Demo 2), plus expense, benefits and PTO projection ([docs/demo-questions.md](demo-questions.md)) ✅ |
| Operational trace | `tool_trace` in every `/chat` response (tool, arguments, result summary, latency), shown in the UI's trace panel; JSON-lines log (`app/agent/trace.py`) ✅ |
| Graceful failures | Unknown employee: `ToolError`, then clarify. No employee: clarify. Provider errors: fallback chain, then `degraded`. MCP down: `/health` shows `connected: false` ✅ |
| No irreversible actions | Tickets are two-phase (proposed, then created only on the user's Confirm); the LLM never sees `confirmation_token`; emails are drafts only (`draft_not_sent`); tests in `tests/test_mcp_server.py`, `tests/test_app.py` ✅ |

## 5. MCP

| Requirement | Evidence |
|---|---|
| MCP server | `hr_mcp/server.py` (official MCP Python SDK 2.3.0, `MCPServer`), stdio subprocess started by the app ✅ |
| At least 5 tools, including a RAG tool and a mock-data tool | 10 tools: `search_policy_documents`, `get_policy_section`, `list_policy_documents`, `lookup_employee_profile`, `check_pto_balance`, `project_pto_balance`, `lookup_benefits_status`, `check_policy_compliance`, `draft_hr_email`, `create_mock_hr_ticket` ✅ |
| The agent really calls MCP | `app/agent/mcp_client.py` (`ClientSession` over stdio, `list_tools` discovery, `call_tool`); no direct function calls ✅ |
| Architecture, transport, schemas and discovery documented | [design-and-evaluation.md](../design-and-evaluation.md) sections 1–4 ✅ |

## 6. Web application

| Requirement | Evidence |
|---|---|
| Chat interface | FastAPI + `app/static/index.html`: employee picker, question library, answer cards, sources, trace, Confirm/Cancel ✅ |
| `/chat` with answer, citations, snippets and trace | `POST /chat`; `POST /chat/confirm` for pending actions ✅ |
| `/health` with MCP status | `GET /health`: app status, `mcp.connected`, `tool_count`, index info ✅ |
| Grader can reproduce two demo tasks | UI question library and `GET /demo-tasks` (dates computed from today, checked by `tests/test_demo_questions.py`); `curl` examples in the README ✅ |

## 7. Deployment

| Requirement | Evidence |
|---|---|
| Free-tier host, shareable URL | Render Blueprint `render.yaml` (free web service) ✅; live URL in [deployed.md](../deployed.md) 🚀 |
| Single service with env vars | Web app, agent, MCP subprocess and FAISS index in one service; keys as Render env vars ✅ |
| No paid database | Index built at deploy time; mock data committed as JSON ✅ |
| Cold start documented | Behaviour documented in [deployed.md](../deployed.md) ✅; measured numbers 🚀 |

## 8. CI/CD

| Requirement | Evidence |
|---|---|
| Runs on push and PR | `.github/workflows/ci.yml` (`push` to main and skapali, `pull_request`) ✅ |
| Install, build/start check, tests | Lint, import check, keyless index build, pytest (241 tests), retrieval ablation, smoke test that starts the app ✅ |
| App start test and MCP discovery test | Smoke test asserts `/health` shows MCP connected with ≥5 tools; `tests/test_mcp_server.py` uses a real stdio `ClientSession` for discovery and calls ✅ |
| Deploy only if tests pass | `deploy` job: `needs: test`, `main` only, calls the Render deploy hook; Render auto-deploy is off ✅ |

## 9. Evaluation

| Requirement | Evidence |
|---|---|
| 20–30 cases with gold answers across all categories | 28 cases in `evaluation/cases.yaml`: 8 single-doc, 5 multi-doc, 8 workflow, 3 ambiguous, 4 adversarial ✅ |
| Groundedness, citation accuracy, partial match | `evaluation/metrics.py` + LLM judge (`evaluation/judge.py`); results in [evaluation/report.md](../evaluation/report.md) ✅ |
| Tool selection, workflow completion, clarify/escalate, action safety | Same report ✅ |
| Latency p50/p95, cold vs warm | Local p50/p95 in the report ✅; deployed warm and cold numbers in `deployed.md` 🚀 |
| At least one ablation | Retrieval top-k × embedder, and full tools vs RAG only on the workflow cases ✅ |

## 10. Design documentation

| Requirement | Evidence |
|---|---|
| Design choices justified | [design-and-evaluation.md](../design-and-evaluation.md); every decision with its reason in [ai-tooling.md](../ai-tooling.md) ✅ |
| Architecture diagram | Mermaid diagrams in the README and design document ✅ |
| Two demo tasks and their MCP call sequences | design-and-evaluation.md and [docs/demo-questions.md](demo-questions.md) ✅ |

## Submission files

| Required | In the repo |
|---|---|
| README.md | ✅ (deployed URL 🚀) |
| design-and-evaluation.md | ✅ |
| ai-tooling.md | ✅ |
| deployed.md | ✅ (URLs and measurements 🚀) |
| evaluation/ | ✅ cases, scripts, results, report |
| mock_data/ | ✅ |
| mcp/ (or equivalent) | ✅ `hr_mcp/` (named so it does not shadow the `mcp` SDK package) |
