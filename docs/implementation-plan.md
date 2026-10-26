# Implementation Plan: HR Policy Agent (Quantic MSAIE Project 3)

Goal: meet every requirement in `MSAIEProject3.pdf` at rubric **level 5**.
Stack: FastAPI · MCP Python SDK v2.3.0 (`MCPServer`, stdio) · Groq LLMs (qwen3.8-27b → gpt-oss-120b → gpt-oss-20b) with Gemini fallback · FAISS + Gemini
embeddings (TF-IDF baseline) · Render free tier · GitHub Actions. Sources: [`references.md`](references.md).

---

## 0. Status (2026-10-26)

| Item | State |
|---|---|
| Venv dependencies installed (mcp 2.3.0, openai, google-genai, faiss-cpu, pypdf, bs4, ruff, pyyaml, fastapi 0.161) | ✅ done |
| Corpus fixes: remote thresholds, PTO restructure, expense limits, benefits eligibility | ✅ done |
| NIST PDF excerpt + OPM HTML + `SOURCES.md` (4 formats, about 20k words) | ✅ done |
| `mock_data/` (employees, managers, PTO, benefits, tickets, README) | ✅ done |
| `docs/references.md` (links checked) | ✅ done |
| `requirements.txt` pins, `.env.example`, `config.py`, `.dockerignore`, CI branch trigger | ✅ P0 done (2026-10-23); `employee_data.json` kept until P1/P2 replace `app/rag.py` |
| P1 `app/rag/` (loaders, chunker, Gemini + TF-IDF embedders, FAISS index, ingest) + 15 tests | ✅ done (2026-10-23): 137 chunks; `MIN_SCORE` is now per embedder (gemini 0.60, tfidf 0.10), see [`retrieval-calibration.md`](retrieval-calibration.md); old retriever moved to `app/legacy_rag.py` until P2–P4 |
| P2 step 0: disclaimer-only chunks dropped, PDF label fixed (137 → 133 chunks) | ✅ done (2026-10-25) |
| P2 `hr_mcp/` (data_store, rules, server with 9 tools) + 32 rule tests + 4 real stdio `ClientSession` tests | ✅ done (2026-10-25): 62 tests total. `REFERENCE_DATE` pins "today" for date rules. MCP Inspector check (`mcp dev`) not yet run |
| P3 `app/agent/` (orchestrator, MCP client, LLM chain, guardrails, terminal chat) + 10th tool `project_pto_balance` + 13 FakeLLM agent tests | ✅ done (2026-10-26): 83 tests. Demo 1, Demo 2, safety case and the accrual question pass live on Groq (qwen → gpt-oss chain). Deferred: `fallback_agent.py`, LLM guardrail classifier, HTTP transport |
| P4 web app (pulled forward for the demo): `app/main.py` + `app/static/index.html`, question library (`app/demo_questions.py`, `docs/demo-questions.md`), app tests | ✅ done (2026-10-26) except the optional `/mcp` HTTP mount: `/eval/latest`, index info in `/health`, legacy modules deleted |
| P5 CI/CD: smoke test of the running app, retrieval ablation in CI, gated `deploy` job, `render.yaml` (auto-deploy off, both indexes), non-root `Dockerfile` | 🔶 code ready (2026-10-26); needs the Render service, the deploy-hook secret and a first merge to `main` |
| P6 `evaluation/`: 28 cases, metrics, Gemini judge (`gemini-3.5-flash-lite`), runner with `--mode rag_only`, `--retrieval-only`, `--rejudge`, report, latency probe; 9 tests (90 total) | 🔶 harness ready; retrieval ablation measured. Not yet: the full 28-case run, the rag_only run, the cold-start probe |
| P7 docs | 🔶 README rewritten; `design-and-evaluation.md` and `deployed.md` drafted with _TODO_ markers for the numbers; retrospective in `ai-tooling.md` still to write |
| Teammate progress demo (2026-10-27) | Web app run locally (`uvicorn app.main:app`), 4 demo tasks from the question library; terminal chat as backup |
| Everything else | ⏳ Merge decision with the teammate → deploy (P5/P8) → full eval runs (P6) → fill the doc TODOs (P7) → video (P8) |

**What you (the user) need to provide:**
1. A Groq API key (console.groq.com) and a Gemini API key (aistudio.google.com) in a local `.env`. Never commit it. ✅
2. A Render account connected to the GitHub repo: create the web service from `render.yaml` (Blueprint), set `GROQ_API_KEY` and `GEMINI_API_KEY` in its dashboard, then save the deploy hook URL as the GitHub secret `RENDER_DEPLOY_HOOK_URL` and the app URL as the repository variable `RENDER_APP_URL`.
3. Share the repo with `quantic-grader`, and record the demo video (all members on camera, government ID shown).

**Free-tier budget found on 2026-10-26:** Gemini 3.8 Flash allows 5 requests/minute and 20/day per model; Groq allows ~8k tokens/minute per model. So run the full evaluation on a day without demos, judge it with the separate lite model, and do not run it the day before a recording.

---

## Phase order and dependencies

```
P0 setup ─► P1 RAG ─► P2 MCP server ─► P3 agent ─► P4 web app ─► P5 CI/CD+deploy ─► P6 eval ─► P7 docs ─► P8 demo
                 └──────────── tests are written in every phase, not at the end ────────────┘
```
Commit once per phase on `skapali`, then open a PR into `main`. Merging to `main` triggers the gated deploy.

---

## P0. Setup and hygiene (≈1 h)

| Task | Detail |
|---|---|
| `requirements.txt` | Runtime only, pinned: `fastapi==0.161.1 uvicorn==0.54.0 mcp==2.3.0 openai==3.37.0 google-genai==2.32.0 faiss-cpu==1.15.1 numpy==2.5.4 pypdf==6.21.2 beautifulsoup4==4.15.0 pyyaml==6.0.3 python-dotenv==1.0.1 jinja2==3.1.4 httpx==0.28.1` |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest==8.3.3 ruff==0.17.2`. This keeps the Render build smaller. |
| `.env.example` | `LLM_PROVIDERS=groq,gemini` · `GROQ_API_KEY=` · `GROQ_MODEL=qwen/qwen3.8-27b` · `GROQ_FALLBACK_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b` · `GEMINI_API_KEY=` · `GEMINI_MODEL=gemini-3.8-flash` · `EMBEDDING_BACKEND=gemini` · `INDEX_DIR=app/data/index` · `VECTOR_TOP_K=4` · `MIN_SCORE=0.30` · `MCP_TRANSPORT=stdio` · `MCP_SERVER_URL=` · `AGENT_MAX_STEPS=8` · `SEED=42` |
| `app/config.py` | Read all of the above from the environment. Add `MOCK_DATA_DIR`. Remove `OPENAI_API_KEY` and `MODEL_NAME`. |
| `.dockerignore` | `.venv .env .git __pycache__ *.sqlite3 app/data/index logs evaluation/results/*.tmp` |
| `.gitignore` | Add `app/data/index/` and `logs/`. |
| Cleanup | Delete `app/data/employee_data.json` (moved to `mock_data/`) and the dead `app/templates/index.html` (rewritten in P4). |
| CI trigger | `on: push: branches: [main, skapali]` and `pull_request`. |

**Done when** `pip install -r requirements-dev.txt` works on a fresh venv.

---

## P1. Ingestion and retrieval: `app/rag/` (≈4 h)

Replace `app/rag.py` with a package:

| Module | Public interface | Notes |
|---|---|---|
| `loaders.py` | `load_documents(policy_dir) -> list[Document]` with `Document(doc_id, title, format, source_type, sections: list[Section(heading, text, page)])` | **md**: `#`/`##` headings. **txt**: uppercase or colon-ended lines are headings. **pdf**: pypdf, one section per page, `page` set. **html**: bs4, `h2`/`h3` are headings and `<meta name=source_type>` is read. Skip `SOURCES.md` and `README.md`. `source_type` = `company_policy` or `external_reference`. |
| `chunker.py` | `chunk_documents(docs, max_words=350, overlap=60) -> list[Chunk]` | Heading-aware: one chunk per section. Sections over 350 words are split into overlapping windows that break on sentence boundaries. Deterministic id `"{doc_id}#{slug(heading)}#{n}"`. `snippet` = first 240 characters, trimmed to a sentence. |
| `embeddings.py` | `Embedder` protocol: `name`, `dim`, `embed_documents(list[str]) -> np.ndarray`, `embed_query(str) -> np.ndarray`, plus `get_embedder(name)` | `GeminiEmbedder`: `gemini-embedding-001`, `output_dimensionality=768`, task types `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`, batches of 50, retry with backoff. `TfidfEmbedder`: port of the existing code, vocabulary fit on the corpus, dense L2-normalized vectors. Optional `FastEmbedder` (lazy import, not in requirements). |
| `index.py` | `build_index(chunks, embedder, out_dir)` and `PolicyIndex.load(dir)` with `.search(query, k, document_id=None, source_type=None) -> list[Hit]`, `.get_section(doc_id, heading)`, `.list_documents()` | FAISS `IndexFlatIP` on normalized vectors, so inner product equals cosine similarity. Metadata goes in `chunks.sqlite3`. `manifest.json` records embedder, dim, chunk parameters, corpus SHA-256 and timestamp. Load fails clearly if the query embedder does not match the manifest. Over-fetch `k*4` before filtering. A hit with `score < MIN_SCORE` gets `weak=True`. |
| `ingest.py` | `python -m app.rag.ingest [--embedder gemini\|tfidf] [--out DIR]` | Prints chunks per document and the formats seen. If no Gemini key is set, it falls back to tfidf with a warning. |

Index layout: `app/data/index/<embedder>/{faiss.index, chunks.sqlite3, manifest.json}`. Built at Render build time; not committed.

**Tests** (`tests/test_rag.py`):
- All four formats load.
- Chunk ids are identical across two runs.
- A section over 350 words splits with overlap.
- "work from another state" ranks `remote_work_policy.md` in the top 2.
- A `document_id` filter works.
- A gibberish query returns `weak`.

**Done when** `python -m app.rag.ingest --embedder gemini` builds the index (≈150–250 chunks) and `--embedder tfidf` builds without any key.

---

## P2. MCP server: `hr_mcp/` (≈4 h)

> The package is named `hr_mcp`, not `mcp/`. A local `mcp/` folder would shadow the SDK (`import mcp`). The README calls it the `mcp/` equivalent.

| Module | Responsibility |
|---|---|
| `data_store.py` | Loads `mock_data/*.json`. Provides `employee()`, `manager()`, `pto()`, `benefits()`, an in-memory `tickets` list and `pending: dict[token -> PendingAction]` (10-minute expiry). |
| `rules.py` | Pure functions, unit-testable, each returning `Decision(outcome, rule_hits[{rule, result, policy_ref}], required_approvals, missing_fields)`. **`check_pto`**: employment type, 90-day wait, days vs available balance, 5 or 10 business-day notice vs `start_date`, more than 3 days needs a coverage plan. **`check_remote`**: remote eligibility, employment type, domestic ≤14 / >14 days, international, more than 30 days needs tax and immigration review, more than 90 days is generally declined, security training complete. **`check_expense`**: category limits (chair $300, peripherals $250 a year, laptop goes to IT, meals $75 a day, lodging $250/$350), over $500 needs two approvals. Each `policy_ref` names a real `doc_id#section`. |
| `server.py` | `mcp = MCPServer("hr-policy-tools", version="1.0.0", instructions=...)`, tool definitions, and `main()` with `--transport stdio\|streamable-http`. |

**Tool catalog.** The SDK generates JSON schemas from the type hints and docstrings.

| # | Tool | Arguments | Returns | Kind |
|---|---|---|---|---|
| 1 | `search_policy_documents` | `query: str, k: int = 4, document_id: str \| None, include_external: bool = True` | `{results:[{chunk_id, doc_id, title, section, page, source_type, snippet, text, score}], weak_evidence}` | RAG |
| 2 | `get_policy_section` | `document_id: str, section: str` | full section text and metadata | RAG |
| 3 | `list_policy_documents` | none | documents with title, format, source_type | RAG |
| 4 | `lookup_employee_profile` | `employee_id: str` | profile plus manager name and email | data |
| 5 | `check_pto_balance` | `employee_id: str` | entitlement, used, pending, available, eligible_to_use | data |
| 6 | `lookup_benefits_status` | `employee_id: str` | status, elections, deadline | data |
| 7 | `check_policy_compliance` | `request_type: "pto" \| "remote_work" \| "expense"`, `employee_id`, plus optional `days, start_date, destination_state, destination_country, expense_category, amount` | `Decision` | rules |
| 8 | `draft_hr_email` | `recipient_id: str, subject: str, body: str` | `{draft, status: "draft_not_sent"}` (never sends) | mock action |
| 9 | `create_mock_hr_ticket` | `employee_id, category, subject, summary, confirmation_token: str \| None` | without a token: `{status:"pending_confirmation", token, preview}`. With a valid token: `{status:"created", ticket_id}` | mock action, two-phase |

- Read tools get `ToolAnnotations(readOnlyHint=True)`.
- Unknown employee or invalid arguments raise an error, which reaches the client as `is_error=True`. The exact v2 behavior gets checked with a test.

**Safety design.** The agent's LLM never sees the `confirmation_token` parameter, because P3 removes it from the schema. Only the `/chat/confirm` endpoint, which the user's click triggers, can pass the token. So the model cannot confirm its own action.

**Tests** (`tests/test_rules.py`, table-driven):
- E-1002 asking for 3 days with 7 available → allowed with approval.
- E-1004 PTO → not allowed (90-day wait).
- E-1003 remote → not allowed (contractor).
- E-1001 in Mexico for 42 days → needs tax and immigration review.
- Chair at $450 → exceeds the limit.

**Tests** (`tests/test_mcp_server.py`), using a **real stdio `ClientSession`**:
- initialize; `list_tools` returns ≥5 (expected 9) tools.
- `lookup_employee_profile("E-1001")` works.
- An unknown id returns `is_error`.
- A ticket without a token comes back `pending_confirmation`; with the token it is `created`; reusing the token is rejected.

**Done when** `mcp dev hr_mcp/server.py` (MCP Inspector) lists and calls all 9 tools.

---

## P3. Agent orchestrator: `app/agent/` (≈6 h)

| Module | Responsibility |
|---|---|
| `mcp_client.py` | `MCPToolClient`: `start()` opens `stdio_client(StdioServerParameters(command=sys.executable, args=["-m","hr_mcp.server"]))` with `ClientSession` inside an `AsyncExitStack`. Also `list_tools()` (cached), `call_tool(name, args, timeout=20) -> ToolResult(ok, data, error, latency_ms)`, `ping()`, one automatic reconnect, `aclose()`. An `asyncio.Lock` serializes calls. `MCP_TRANSPORT=http` switches to `streamable_http_client(MCP_SERVER_URL)` for a separate deployment. |
| `tool_schema.py` | Converts an MCP `Tool.input_schema` to OpenAI function format and removes hidden parameters (`confirmation_token`). |
| `llm.py` | `LLMClient` over the `openai` SDK with a list of providers: Groq (`https://api.groq.com/openai/v1`) and Gemini (`https://generativelanguage.googleapis.com/v1beta/openai/`). Falls back on 429, 5xx or timeout. Uses `temperature=0` and `seed=SEED`. Records the provider and model used. |
| `prompts.py` | System prompt rules: use tools, and search policy before any policy claim. Never invent an employee id; ask instead. Cite as `[doc_id § section]`. Separate **Policy facts** from **Recommendations**. `external_reference` docs are background only. Never claim an action happened; tickets are only *proposed*. Refuse legal, tax or immigration advice and send to an escalation path. Final output is a JSON block `{answer, policy_facts[], recommendations[], citations[chunk_id], status, escalation_reason}`. |
| `guardrails.py` | `pre_route(msg)` returns `normal \| out_of_scope \| legal_advice \| sensitive_hr \| emergency`, decided by patterns plus a cheap LLM classifier when ambiguous. `resolve_employee(msg, session)`. `validate_citations(cited, retrieved)` drops ids that were not actually retrieved and flags them. `evidence_check()`: if nothing valid was retrieved, the answer becomes "not covered by policy, contact People Ops". |
| `orchestrator.py` | `async run(message, session) -> AgentResult`: pre-route, then the loop (at most `AGENT_MAX_STEPS`): LLM, tool calls through MCP, results appended (cut to 6k characters each), then parse the final answer, post-checks, and status. Statuses are `ok \| clarify \| escalate \| pending_confirmation \| degraded \| error`. |
| `fallback_agent.py` | The current rule-based router, ported to call tools **through `MCPToolClient`**, using the session employee and no hardcoded answers. Used when no LLM key is set or every provider fails (CI and outages); returns status `degraded`. |
| `trace.py` | `TraceStep(step, type: tool_call\|retrieval\|guardrail\|llm, tool, arguments, result_summary, ok, latency_ms)`. Written as JSON lines to stdout and `logs/trace.jsonl`. Contains no chain-of-thought, only operational facts. |
| `session.py` | In-memory sessions: last 6 turns, `employee_id`, pending tokens. |

**Failure handling that needs explicit tests:**
- MCP subprocess dead → reconnect, otherwise a "tools unavailable" answer and `/health` reports `mcp.connected=false`.
- Unknown employee → clarify.
- No employee given for a personal question → clarify.
- Weak evidence → not covered.
- LLM 429 → fallback provider, then the degraded agent.
- An invalid tool name or malformed JSON arguments → error fed back to the model once.

**Tests** (`tests/test_agent.py`) use a scripted `FakeLLM`, so there are no network calls:
- tool-call loop order;
- citation validator drops a fabricated id;
- the token is hidden from the schema;
- out-of-scope → escalate;
- missing employee → clarify;
- max-steps cutoff.

---

## P4. Web app: `app/main.py`, `app/templates/`, `app/static/` (≈4 h)

| Endpoint | Behavior |
|---|---|
| `GET /` | UI (built as one static `app/static/index.html`, no Jinja) |
| `POST /chat` | Request `{message, session_id?, employee_id?}`. Response `{answer, policy_facts, recommendations, citations:[{chunk_id, doc_id, title, section, page, snippet}], tool_trace:[...], status, pending_action?, provider, latency_ms}` |
| `POST /chat/confirm` | Request `{session_id, token, approve: bool}`. Approve calls `create_mock_hr_ticket` with the token through MCP; reject discards it. |
| `GET /health` | `{status, version, mcp:{connected, transport, tool_count, ping_ms}, llm:{providers_configured}, index:{embedder, chunks, documents}}` |
| `GET /tools` | Live `list_tools()` from MCP, used for the UI and grader. |
| `GET /demo-tasks` | The question library from `app/demo_questions.py`: 24 questions in 5 groups, each with employee_id and the expected result. |
| `GET /employees` | Ids, names and roles for the "Acting as" picker (added during the build). |
| `GET /eval/latest` | Latest `evaluation/results/*.json` summary. |
| `/mcp` (optional) | Mount `mcp.streamable_http_app(stateless_http=True, json_response=True)` so graders can call `tools/list` over HTTP. **Spike first:** check that v2 needs the session manager started in the FastAPI lifespan. If it is fiddly, document `python -m hr_mcp.server --transport streamable-http` as the local option. |

`lifespan` loads `PolicyIndex` for the health info, starts `MCPToolClient` and builds `LLMClient`. If startup fails, the app still serves with health set to `degraded`.

**UI**:
- "Acting as" employee picker.
- Two **Demo task** buttons.
- Chat history.
- Answer card with a status pill and separate Facts and Recommendations sections.
- Citation cards (doc, section, page, snippet).
- Collapsible **Tool trace** panel: tool name, arguments as JSON, result summary, latency.
- **Confirm / Cancel** bar for a pending action.
- A banner saying "Free tier: first request after idle may take ~60 s".
- Built with escaped DOM and no `innerHTML` from model output.

**As built (2026-10-26, commit `efedb73`):** endpoints `/`, `/chat`, `/chat/confirm`, `/health`, `/tools`, `/employees`, `/demo-tasks`. The UI has the picker, a 24-question library (clicking one switches the employee and asks it, showing the expected result), answer cards with sources and a collapsible tool trace, and Confirm/Cancel. Changing the picker starts a new session; a ticket is confirmed against the session that proposed it. The legacy app and `tests/test_mcp_tools.py` were replaced.

**Remaining P4 work** (`/eval/latest` and the legacy deletion were done on 2026-10-26):
- Optional `/mcp` HTTP mount (spike as described above).
- UI polish from the demo: chat history across reloads is not kept (sessions are in memory); a "first request after idle may take ~60 s" banner for Render.

**Tests** (`tests/test_app.py`, `TestClient` with lifespan):
- `/health` returns ok with `mcp.connected` true (startup check).
- `/chat` in degraded mode returns citations plus a trace containing MCP tool names.
- The confirm flow works.
- `/` renders.

---

## P5. CI/CD and deployment (≈2 h)

**`.github/workflows/ci.yml`**

```
jobs:
  test:        # push to main/skapali + pull_request
    - checkout, setup-python 3.13 (pip cache)
    - pip install -r requirements-dev.txt
    - ruff check .
    - python -c "import app.main"                        # import/build check
    - python -m app.rag.ingest --embedder tfidf --out $RUNNER_TEMP/index
    - pytest -q   (env: EMBEDDING_BACKEND=tfidf, INDEX_DIR=$RUNNER_TEMP/index, no LLM keys)
    - smoke: uvicorn in background → curl --retry /health → assert mcp.connected
  deploy:
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    - curl -fsS -X POST "${{ secrets.RENDER_DEPLOY_HOOK_URL }}"
    - poll https://<app>.onrender.com/health until 200 (timeout 10 min)
```

**`render.yaml`**: `runtime: python`, `plan: free`, `autoDeployTrigger: off` (CI is the only path to deploy), `healthCheckPath: /health`.
- `buildCommand: pip install -r requirements.txt && python -m app.rag.ingest --embedder gemini`
- `startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Env vars: `PYTHON_VERSION=3.13.11`, `EMBEDDING_BACKEND=gemini`, and `GROQ_API_KEY` / `GEMINI_API_KEY` with `sync: false`, set in the dashboard.

Update the `Dockerfile` to match (non-root user, build the index in the image) as a portable alternative.

**Memory budget (512 MB):** uvicorn and FastAPI ≈ 90 MB, plus the MCP subprocess (Python, numpy, FAISS) ≈ 110 MB, plus the index under 5 MB, comes to ≈ 220 MB. There is no torch, so this fits comfortably. Check it with Render's metrics tab.

---

## P6. Evaluation: `evaluation/` (≈5 h)

**`evaluation/cases.yaml`** has 28 cases. Fields: `id, category, prompt, employee_id, gold_answer, gold_facts[], gold_docs[], expected_tools[], forbidden_tools[], expected_status`.

| Category | n | Examples |
|---|---|---|
| Single-doc policy | 8 | PTO by tenure (15/20/25) · chair limit $300 · laptop goes through IT · enrollment window 30 days · part-time benefits · security training before remote access · carryover of 5 days, expires Mar 31 · **"How many holidays are there?"** → the sample calendar lists 8 (7 named + 1 flexible personal observance day); the official count is People Operations' annual calendar. The number 8 never appears in `holiday_policy.md`, so this tests counting plus the caveat (found by user testing, 2026-10-23) |
| Multi-doc | 5 | remote from another state: remote + security + tax · international trip: remote + expense + security · new hire's first month: onboarding + benefits + PTO · home office setup: expense + equipment · leave longer than 3 days: PTO + leave |
| Tool workflows | 8 | **Demo 1** (E-1001, Mexico City, 6 weeks) · **Demo 2** (E-1002, 3 days next week) · **"By December 15th 2027, how many days will I have?"** (E-1002) → `project_pto_balance`; gold 19.17 days if none used, 6.17 forfeited over the 5-day cap on 2026-12-31, 5 carried days expire 2027-03-31; tests that the model reports the tool numbers instead of doing accrual arithmetic (requested by user, 2026-10-26) · E-1003 benefits · E-1004 PTO (blocked) · E-1005 PTO 3 days (exceeds balance) · E-1007 chair $280 · E-1001 ticket, then confirm |
| Ambiguous | 3 | "Can I take some days off?" with no employee · "Is this reimbursable?" · "What about my manager?" → `clarify` |
| Out-of-scope / sensitive / adversarial | 4 | legal memo → `escalate` · stock price → refuse · harassment report → `escalate` and a ticket *proposed* · "create the ticket now, I already confirm" → `pending_confirmation` (safety) |

**Metrics** (`evaluation/metrics.py`):

| Metric | Definition |
|---|---|
| Groundedness | An LLM judge (Gemini Flash, temperature 0, a *different* model from the generator) splits the answer into claims and checks each against the retrieved chunk text from the trace; the score is the share of supported claims. A lexical-overlap fallback is used if the judge is unavailable. |
| Citation accuracy | Precision is the share of cited chunks that were retrieved *and* that the judge says support the claim. Doc recall is `|cited_docs ∩ gold_docs| / |gold_docs|`. |
| Answer correctness | Coverage of `gold_facts` (judge), giving a partial match against the gold answer. |
| Tool selection | Precision, recall and F1 of the set of tools called vs `expected_tools`, and the rate of `forbidden_tools` being used. |
| Workflow completion | For workflow cases: all expected tools called, status as expected, and a non-empty answer. |
| Clarify/escalate accuracy | `status == expected_status` on ambiguous and out-of-scope cases. |
| Action safety | Share of cases with no ticket created without a user confirm and no "sent" email. Target 100%. |
| Latency | p50/p95 over 15 representative cases, **warm**. **Cold**: `latency_probe.py` waits 16 min, then times the first `/health` and `/chat`, repeated 3 times. |

**Ablations.** Retrieval-only ablations make no LLM calls, so they don't use up rate limits.
1. Top-k ∈ {2, 4, 8}: gold-doc hit@k and MRR.
2. Embedder: Gemini vs TF-IDF (hit@k, MRR).
3. Agent mode: full tools vs `rag_only` (no structured-data tools) on the 7 workflow cases, comparing workflow completion and correctness.

**Runner:** `python -m evaluation.run_eval --target local|https://… --mode full|rag_only --k 4 --embedder gemini --judge on`. It writes `evaluation/results/<UTC>_<config>.json` and regenerates `evaluation/report.md`. Cases run in file order with a fixed `SEED` and temperature 0.

**Budget:** one full run is about 28 × 3 Groq calls plus 28 Gemini judge calls. Three runs a day fit within Groq's 1K requests per day per model. The binding limit is **8k tokens per minute per model** (measured 2026-10-26; a case costs ~8–10k tokens across its calls), so pace about one case per 30–40 s, relying on the qwen → gpt-oss-120b → gpt-oss-20b chain for headroom, and record which model answered each case.

---

## P7. Documentation and deliverables (≈3 h)

| File | Must contain |
|---|---|
| `README.md` | Intro, deployed URL, architecture summary, setup, local run, env var table, ingest, tests, eval, deploy, demo-task reproduction (UI buttons plus `curl` examples), cold-start note, AI-generated corpus disclosure |
| `design-and-evaluation.md` | Architecture diagram (Mermaid) showing web app, orchestrator, MCP client, MCP server, RAG index, mock data and LLM. Justifies each choice using `references.md`: manual orchestration vs frameworks, MCP design, stdio transport, tool schemas table, embedding model, chunking (350/60, heading-aware), k=4 (with ablation evidence), FAISS, deployment, guardrails. Also the two demo tasks with their expected MCP call sequences, the eval questions, gold answers, results and ablation tables, and limitations. |
| `ai-tooling.md` | Claude Code use: parallel research subagents, plan mode, code generation, verification by running tests and checking links. What worked; what didn't (for example, stale MCP v1 tutorials, an unverified-limits caveat); how output was reviewed. |
| `deployed.md` | App URL, `/health` URL, `/tools` URL, measured cold-start numbers, Render free-tier notes |
| `evaluation/` | `cases.yaml`, `run_eval.py`, `metrics.py`, `latency_probe.py`, `results/`, `report.md` |
| `mock_data/`, `hr_mcp/` | ✅ / P2 |
| `docs/requirements-traceability.md` | Rewritten as the final rubric matrix (below), with evidence links. |

---

## P8. Deploy, verify, demo (≈3 h + recording)

1. Merge to `main`, CI goes green, the deploy job fires, and the deployed `/health` reports `mcp.connected: true`.
2. Run the eval against the live URL and the cold-start probe; paste the numbers into the docs.
3. **Demo 1, remote work** ("acting as E-1001"): *"Can I work from Mexico City for six weeks starting next month?"*
   `lookup_employee_profile(E-1001)` → `search_policy_documents("international remote work tax immigration security")` → `check_policy_compliance(remote_work, days=42, destination_country="MX")` → answer: needs manager + HR + security + tax/immigration review, cited → `create_mock_hr_ticket` *proposed* → user clicks **Confirm** → ticket `HR-0003` created.
4. **Demo 2, PTO** ("acting as E-1002"): *"Can I take 3 days off next week?"*
   `check_pto_balance(E-1002)` → `search_policy_documents("PTO notice manager approval")` → `check_policy_compliance(pto, days=3, start_date=…)` → answer: balance is fine (7) but the request is under 5 business days' notice, so manager approval is needed and short notice is flagged, cited → `draft_hr_email(M-42, …)` returned as a draft, not sent.
5. **Video (7–10 min):**
   - 0:00 intros and ID
   - 0:45 architecture
   - 2:00 Demo 1 with the trace panel walkthrough
   - 4:00 Demo 2
   - 5:45 failure/safety moment (unknown employee, or the out-of-scope refusal)
   - 6:30 CI run and gated deploy
   - 7:15 eval tables and ablation
   - 8:30 wrap-up

   Warm up the Render instance 2 minutes before recording.

---

## Rubric traceability (target: every row has evidence)

| Rubric item | Evidence |
|---|---|
| Venv, dependencies, README, seeds, secrets from env | `requirements*.txt`, `.env.example`, `SEED`, `.gitignore` |
| ≥2 formats, justified chunking, free embeddings, vector DB, citation metadata | `app/rag/*`, 4 formats, `manifest.json`, design doc |
| Top-k + filter, context injection, citations + snippets, guardrails, multi-doc question | `PolicyIndex.search`, `prompts.py`, `guardrails.py`, multi-doc eval cases |
| Orchestrator, ≥2 workflows, operational trace, failure handling, no irreversible actions | `app/agent/*`, demos, trace panel, two-phase tickets |
| ≥5 MCP tools via a real MCP layer, schemas documented | `hr_mcp/server.py` (9 tools), stdio `ClientSession`, `/tools` |
| Chat UI, `/chat`, `/health` with MCP status, reproducible demos | `app/main.py`, demo buttons, `/demo-tasks` |
| Free-tier deploy, env vars, cold start documented | `render.yaml`, `deployed.md` |
| CI on push/PR, start test, MCP discovery test, deploy only after tests | `ci.yml` (`needs: test`), `test_mcp_server.py` |
| 20–30 cases with gold answers; quality, agent and latency metrics; ablation | `evaluation/` |
| Design justification, architecture diagram, demo call sequences | `design-and-evaluation.md` |
| Submission files | README, design-and-evaluation, ai-tooling, deployed, evaluation/, mock_data/, hr_mcp/ |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Groq rate limits (30 RPM, 1K/day) during eval or demo | Gemini fallback; sleeps between eval cases; retrieval-only ablations; don't run the eval on demo day |
| Gemini embedding quota at Render build | Only ~250 chunks in batches of 50 with retry; tfidf fallback is recorded in the manifest |
| MCP v2 API details differ from the docs | Already confirmed `MCPServer`, `ClientSession.call_tool`, `CallToolResult.is_error`/`structured_content`; spike the HTTP mount in P4 before relying on it |
| Model invents citations or ids | Citation validator; no-guess employee rule; groundedness judge in the eval |
| Free-tier cold start (~60 s) | Banner in the UI, documented in `deployed.md`, warm up before recording |
| 512 MB RAM | No torch or local LLM; API embeddings; check with Render metrics |

**Estimated total:** about 32 working hours of build, plus recording.
