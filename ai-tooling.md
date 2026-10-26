# AI tooling

How AI tools were used to build the HR Policy Agent, what they were good at, and
what they got wrong. This file has two parts:

1. **Session log**: the prompts given and the actions taken, written as the work happens.
   Each entry gets added at the end of a session, not reconstructed later.
2. **Retrospective**: what worked, what needed manual correction, and how that
   changed the way the tools were used. Filled in from the log during P7.

Every correction recorded here happened on this project. None of them are general cautions.

## Tools

| Tool | Used for |
| --- | --- |
| **Claude Code** (Anthropic, Claude Opus) | The main tool. A terminal agent that reads and writes files in the repo, runs shell commands and tests, and checks links. Started in plan mode, then built phase by phase against `docs/implementation-plan.md`. |
| **Claude Code research subagents** | Parallel web research during planning: MCP SDK v2 API, Groq and Gemini free-tier limits, Render free tier, chunking and embedding choices. The links they found are in `docs/references.md`. |
| **RESUME_PROMPT.txt** (outside the repo) | A handoff note between sessions that records the repo state, the decisions already made, the verified APIs and the gotchas. It means a new session doesn't re-ask settled questions. |

## Team approach

Two teammates each build the complete app independently, on separate branches (`skapali` is
this one). Then we compare the two and merge the stronger approach for each component. To make
the comparison fair:

- Both builds use the same frozen corpus (`app/data/policies/`), the same `mock_data/`, the
  same `evaluation/cases.yaml` and the same metrics, so the scores are comparable.
- The comparison happens per component: RAG, MCP tools, agent, UI, CI/CD, eval. The final
  version can take the retriever from one build and the agent from the other.
- The decision and the evidence behind each choice go in `design-and-evaluation.md`.

## Session log

Format for each entry: date · the prompt (quoted or summarised) · what the AI did · what was
verified · any corrections.

### Session 1 (2026-10-22): planning, corpus and mock data

- **Prompt (summarised):** read the `MSAIEProject3.pdf` brief, then build a plan that
  reaches rubric score 5.
- **Actions:**
  - Read the brief and audited the existing scaffold. Found that the original code bypassed MCP
    entirely and had no LLM.
  - Ran research subagents in parallel on the MCP SDK v2, LLM providers, embeddings and hosting.
  - Wrote `docs/implementation-plan.md` (phases P0–P8) and `docs/references.md`.
  - Fixed policy contradictions: single remote-work thresholds, PTO rebuilt as one ordered
    document, explicit expense limits, benefits eligibility.
  - Added the NIST SP 800-46 PDF excerpt and the OPM HTML fact sheet (4 formats).
  - Created `mock_data/` with edge-case employees.
- **Verified:** the 9 existing tests pass; links in `references.md` resolve; the MCP v2 API
  names were checked against the installed SDK (`MCPServer`, `ClientSession.call_tool`,
  `CallToolResult.is_error`).
- **Corrections:**
  - Most tutorials online describe MCP v1 (`FastMCP`, camelCase result fields). v2 renamed
    these, so the API was checked against the installed package instead of the tutorials.
  - A local package named `mcp/` would shadow the SDK import, so the package is called `hr_mcp/`.
- **Commit:** f88984d.

### Session 2 (2026-10-23): resume, AI log, P0 setup

- **Prompt:** "resume using the resume prompt file and also create an ai-tooling.md file … so
  we can log the prompts and actions taken by AI for this project."
- **Actions:**
  - Checked the repo state (git log, pytest: 9 passed). Created this file.
  - P0: pinned runtime-only `requirements.txt` and a separate `requirements-dev.txt`. Rewrote
    `.env.example` and `app/config.py` for Groq/Gemini/embeddings/MCP settings. Added
    `.dockerignore` and `.gitattributes`; extended `.gitignore`. CI now triggers on `skapali`,
    installs the dev requirements and runs `ruff check`. Deleted the unused
    `app/templates/index.html` (`/` serves inline HTML).
- **Verified:** a brand-new venv installs `requirements-dev.txt` and passes all 9 tests.
  `ruff check .` is clean. The malformed-JSON request to `/mcp` still returns a JSON-RPC
  `-32700` after the exception was narrowed.
- **Corrections / deviations:**
  - The plan said to delete `app/data/employee_data.json` in P0, but `app/rag.py` still reads
    it, so deleting it would break the tests. It stays until P1/P2 replace that code.
  - Ruff 0.17's default rules flagged a blind `except Exception` around `request.json()`.
    It was narrowed to `ValueError`, the base class of `json.JSONDecodeError`, rather than
    suppressed. The narrowed path was then exercised to confirm it still returns `-32700`.
  - **A commit that silently missed its files.** The AI passed an already-`git rm`'d path to
    `git add`. Git aborted the whole add with a pathspec error, nothing was staged, and the
    `git commit` chained after it still succeeded, recording only the deletion under a message
    describing 13 files. It was caught by reading `git show --stat` and amended before any
    push. Lesson: check what a commit contains, not just that it ran.

- **Prompt:** "added keys to .env file for groq and gemini", then the AI Studio get-started link
  and a pasted note about `gemini-embedding-001`.
- **Actions:** smoke-tested each key with a one-word call, without ever printing the keys.
  - Groq (`openai/gpt-oss-120b`) answered "OK" at once.
  - Gemini `gemini-embedding-001` returned 768 dimensions.
  - Gemini chat with `gemini-2.5-flash` returned **404 "no longer available to new users"**.
  - Listed the models this key can use and checked the AI Studio page the user linked. That
    page names `gemini-3.8-flash` as the default, so `config.py`, `.env.example`, the plan and
    `references.md` were updated to it.
- **Measured:** `gemini-3.8-flash` answered "OK" after about 63 s on both the native SDK and the
  OpenAI-compatible endpoint. Later calls timed out (90 s) or got an instant
  503 "high demand". `gemini-3.5-flash-lite` answered in about 20 s.
- **Corrections:**
  - The plan's fallback model, chosen during research a day earlier, was already retired for
    new keys. Model names from planning research go stale fast and need a live call to confirm.
  - The 404 message suggested a replacement model. It was checked against the live model list
    and the official page before being adopted, not taken on trust.
  - A first `models.list()` call with no timeout hung for over 2 minutes with no output. It
    was rerun with explicit timeouts and `max_retries=0`. Consequence for P3: every LLM call
    needs a hard timeout, otherwise the "fallback" chain just waits forever.
  - The pasted note mentioned "public API keys from GitHub". The team uses only its own AI
    Studio keys; keys found on GitHub are leaked credentials.

- **Prompt:** "should groq be primary and gemini backup". **Answer:** yes. The evidence was the
  measured latency (Groq instant, Gemini 63 s or 503), two separate providers for redundancy,
  and Gemini then being a *different* model to act as the eval judge. No code change: the order
  is `LLM_PROVIDERS` in `.env`.

- **Prompt:** "yes start P1", then mid-task: "I want to use this opportunity to understand RAG
  better as well".
- **Actions:**
  - Built `app/rag/`: `loaders.py` (md/txt/pdf/html; `source_type` and URL read from
    `SOURCES.md` or the HTML `<meta>`), `chunker.py` (heading-aware, 350/60, contextual header
    for embedding), `embeddings.py` (Gemini + TF-IDF), `index.py` (FAISS + SQLite +
    manifest), `ingest.py`.
  - Moved the old retriever to `app/legacy_rag.py`, since `app/rag.py` and `app/rag/` cannot
    coexist.
  - Built both indexes and ran a side-by-side comparison of 9 queries. The results are in
    `docs/retrieval-calibration.md`.
  - Explained RAG concepts against the real output, as the user asked.
  - Wrote 15 tests in `tests/test_rag.py`. CI now builds the TF-IDF index.
- **Verified:** 24/24 tests and ruff clean. The overlap test was mutation-checked: it fails
  with `overlap=0`. The CI ingest command ran locally. The Gemini index built in 96 s with no
  retries after pacing was added.
- **Corrections:**
  - **Terminal mojibake taken for file corruption (twice).** The Windows console showed `�`
    for `’`, `½` and non-breaking spaces in the PDF and HTML output. The AI first concluded the
    HTML file was corrupted and nearly "repaired" it. Counting `U+FFFD` in the file found
    zero. Lesson: inspect bytes or escaped output (`backslashreplace`) before deciding data
    is broken.
  - **A print truncation read as a parser bug.** The table row looked like it had 2 of its 4
    cells because the AI's own `[:600]` preview cut it off. The same mistake happened with an
    80-character preview that seemed to show missing overlap. This is the CafeFlausse
    "truncated output → wrong conclusion" failure again.
  - **The Gemini quota counts texts, not requests.** The first build hit
    429 `embed_content_free_tier_requests, limit: 100`. Batches of 50 were 3 calls but 150
    texts. The fixed exponential backoff (2–16 s) was also shorter than the server's 27 s
    `retryDelay`. Fixed by pacing to 90 texts a minute and honouring `retryDelay`. The ingest
    fallback built TF-IDF as designed, but it left an empty `gemini/` directory, so embedding
    now happens before the folder is created.
  - **The plan's `MIN_SCORE=0.30` was wrong for both embedders.** Measured Gemini scores were
    0.61–0.77 for relevant hits and 0.50–0.59 for nonsense. The threshold is now per embedder
    and calibrated on data, and the docs state that it is a weak signal.
  - A docstring inserted with `sed` landed after `from __future__` (so it was not a docstring),
    and a second `sed` left a stray `n`. Both were caught by reading the file head. Later bulk
    edits used Python `str.replace` with `assert s.count(old) == 1`, so a replacement that
    matches nothing fails loudly.

- **Prompt:** "commit now and will start p2 later. also generate a nice summary of what was done",
  then "push to wrap up p1 and create a file so i can test".
- **Actions:**
  - Published a Day 2 recap page for the teammate.
  - Updated `RESUME_PROMPT.txt` (outside the repo) for session 3.
  - Added `app/rag/explore.py`, a hands-on search tool showing both embedders side by side.
  - Pushed P0–P1 to `skapali`.
- **Verified:** explore was run in one-shot and in piped interactive mode before committing.
- **Corrections:**
  - The first explore output used box-drawing characters and `§`, which a cp1252 Windows console
    prints as `?`. Switched to ASCII.
  - The test run found that "Do we get free lunch?" scores 0.616 with Gemini, above the 0.60
    cutoff. This is more evidence that the score measures topic similarity, not whether the
    question is answered. Recorded in `docs/retrieval-calibration.md`.
  - A Python `str.replace` sent through the shell had its `\n` escape mangled. The
    `assert count == 1` guard caught it before anything was written, and the edit was redone
    with the Edit tool.
  - **The first CI run on `skapali` failed, while every local run had passed.** The cause was
    `ModuleNotFoundError: No module named 'app'` at test collection. Locally the AI always ran
    `python -m pytest`, which adds the current directory to `sys.path`. CI runs the bare
    `pytest` entry point, which doesn't. The earlier "fresh venv" check also used `-m`, so it
    hid the problem too. The failure was reproduced locally with `.venv/Scripts/pytest.exe`,
    then fixed with `pyproject.toml` (`pythonpath = ["."]`). Lesson: run the exact command CI
    runs, and treat a green CI run, not a green local run, as the proof.
  - **A made-up commit hash.** While updating the Day 2 recap with the push and CI result, the
    AI wrote the latest commit as `e47c4b1`. It had never seen that commit's hash: the commit
    command had printed only the file list. The AI noticed right after publishing, checked
    `git log` (the real hash is `43f9ccf`) and republished. Lesson: any identifier put in a
    shared document must be copied from tool output in this session, never filled in from memory.

- **User testing (no code change):** the user ran `explore` with "how many total holidays?".
  - Gemini's #1 chunk contained the answer, but only in the full text, not the snippet. The
    policy lists 8 holidays and never states the number.
  - The test also showed that disclaimer-only "Overview" chunks in 4 policies take up top-k
    slots, and that PDF hits print "Page 4, page 4".
  - Fix deferred to the start of P2 at the user's request; it is recorded in
    `RESUME_PROMPT.txt` as P2 step 0. The point for the retrospective: the user's own hands-on
    test found a retrieval-quality issue that the 24 tests and the AI's 9-query comparison had
    missed.

### Session 3 (2026-10-25): P2 step 0 (retrieval fix) and P2 MCP server

- **Prompt:** "read the resume prompt file … and proceed from there". Mid-task: "ensure all
  decisions are logged to ai-tooling.md". From then on, every design decision in this session
  is recorded below with its reason, as it is made rather than at the end.
- **State confirmed at start:** branch `skapali` up to date with origin (`43f9ccf`), 24/24
  tests, ruff clean. The only uncommitted change was the end of the session 2 log.

**P2 step 0: disclaimer chunks and the PDF label**
- **Actions:**
  - Captured the "before" output of `explore "how many total holidays?"` on the real indexes
    before changing any code.
  - `chunker.py`: added `is_disclaimer_only()`; `chunk_documents` skips those sections.
  - `explore.py`: moved the hit label into `hit_label()`, which omits ", page N" when the
    section is already "Page N".
  - Two new tests. Rebuilt both indexes (137 → 133 chunks: exactly the 4 disclaimers removed).
  - Added the holiday-count case to the P6 plan (now 27 cases).
- **Verified:** 26/26 tests, ruff clean. After the fix, Gemini's top 4 for the holiday question
  has no disclaimer: slot 2 moved from `Overview` (0.672, no content) to `Purpose and Scope`, and
  `Eligibility and Pay Questions` (0.646) entered at slot 4. The PDF label now reads
  `Page 4 [external]`. The holiday list was re-read in the source: 7 named holidays + 1 flexible
  day = 8, and "8" never appears in the text.
- **Observation:** Gemini scores of the surviving chunks did not change (each dense vector is
  computed per chunk). TF-IDF scores moved slightly (0.111 → 0.110) because IDF depends on the
  whole corpus. Any corpus edit changes every TF-IDF vector, but only the edited chunks of a
  dense index.

**Decisions (with reasons)**
1. *Disclaimers are dropped at ingestion, not filtered at ranking.* The disclaimer chunk scored
   0.672, above real content, because its title header ("Company Holiday … Policy > Overview")
   matches the query. No score threshold can separate it, so it must never enter the index.
2. *Match the disclaimer text plus a 60-word cap, not the "Overview" heading.* Other Overview
   sections hold real rules, and the cap keeps a section that starts with the disclaimer but
   continues with policy text. A test covers both cases.
3. *The holiday eval case goes into the P6 plan now*, because `evaluation/cases.yaml` doesn't
   exist until P6. Case counts and the call budget were updated to 27.
4. *MCP errors: only `ToolError` is shown to the model.* This was read from the installed SDK
   source (`mcp/server/mcpserver/exceptions.py`, `server.py:437-456`), which closes an open item
   from session 2. Any other exception reaches the client only as "Error executing tool X".
   So `data_store` and `rules` raise ordinary `LookupError`/`ValueError` (testable without MCP),
   and `server.py` converts them to `ToolError` at the boundary.
5. *Package layout follows the plan:* `hr_mcp/` (not `mcp/`, which would shadow the SDK), built
   alongside the legacy `app/mcp_server.py`. The legacy module stays until P3/P4 replace
   `app/main.py`, so the existing tests keep passing.
6. *The ticket token is bound to its payload.* `confirm()` rejects a token when the arguments
   differ from the proposed ones, so the user cannot approve one preview and get a different
   ticket. Tokens are random (`secrets.token_urlsafe`), single-use and expire after 10 minutes.
   The clock is injectable, so expiry is tested without sleeping.
7. *`draft_hr_email` recipients:* an employee id, a manager id, or `PEOPLE-OPS`
   (people.ops@example.com), resolved from the mock data so the model cannot invent addresses.
8. *New config `REFERENCE_DATE`* (optional, YYYY-MM-DD) is "today" for the date rules. With the
   real date, the 90-day wait and notice checks give different answers on different days, which
   would make eval runs irreproducible. Added to `.env.example`.
9. *Rules return a `Decision`; the LLM explains it, it does not decide.* Outcome precedence is
   one function: any `fail` → `not_allowed`; else missing input → `needs_info`; else any
   `review` → `needs_review`; else approvals → `allowed_with_approval`; else `allowed`.
10. *`policy_ref` is "doc_id#Exact Heading"*, which can be passed straight to
    `get_policy_section`. A test checks that every reference exists in the loaded corpus.
11. *Policy readings encoded in `rules.py`* (each is a judgement call on the synthetic text):
    - PTO notice counts weekdays from today (inclusive) to the start date (exclusive), so
      Monday to next Monday is 5 business days. Holidays are not subtracted because the
      calendar isn't in the data.
    - Short notice and exceeding the balance are `fail` (the policy says "requires" / "may not"),
      and the detail points to the emergency process or People Operations' unpaid-leave option.
    - The 90-day wait is checked against the PTO *start date*, not today. E-1004 can plan PTO
      that starts after 2027-01-03.
    - Remote: international over 90 days is `fail` ("generally declined"; exceptions need every
      owner). Domestic ≤14 days is allowed only after confirming the approved-state map (no map
      data, so `action_required`), and it becomes a compliance `review` for employees who handle
      restricted data (E-1005, E-1006), per "Short-Term Domestic Work".
    - Incomplete security training blocks remote work (E-1004), per "Security and Equipment
      Requirements".
    - Expenses: a laptop is always `fail` (IT issues it); over $500 adds budget-owner approval;
      home internet requires remote eligibility. The "once every 3 years" and "per year total"
      limits are stated but not checked, because there is no purchase history in the data.
12. *`search_policy_documents(include_external=False)` uses the index's own `source_type`
    filter.* The first draft searched twice and filtered in Python, which was redundant because
    `PolicyIndex.search` already over-fetches when filtering. Fixed before the first test run.
13. *The index and data store open lazily* (`functools.cache`). The server answers
    `initialize`/`list_tools` even if the index is missing, and only the search tools fail.
14. *Async MCP tests use `anyio.run()` inside ordinary sync tests* rather than adding
    pytest-asyncio. anyio already ships with the SDK, so there are no new dependencies. Each
    test starts its own server subprocess (about 3 s each), which is acceptable at 4 tests.
15. *MCP tests are hermetic.* The fixture builds a TF-IDF index in a temp directory and passes
    `INDEX_DIR`, `EMBEDDING_BACKEND=tfidf` and `REFERENCE_DATE=2026-10-22` through the
    subprocess environment. They need no key and give the same result on any day and in CI.
    (`load_dotenv` does not override variables already set, so the passed values win over
    `.env`.)
16. *The streamable-HTTP transport binds 0.0.0.0 on `MCP_HTTP_PORT` (default 8765)*, ready
    for a container. It is not tested yet; mounting it inside FastAPI is a P4 decision.

**P2: MCP server**
- **Actions:** `hr_mcp/__init__.py`, `data_store.py`, `rules.py`, `server.py` (9 tools);
  `tests/test_rules.py` (32 table-driven tests: PTO, remote and expense rules, business-day
  counting, every `policy_ref` resolves, lookups, token single-use/binding/expiry with an
  injected clock); `tests/test_mcp_server.py` (4 tests over a real stdio `ClientSession`:
  tool list and annotations, data tools, `is_error` for an unknown id and a bad date, compliance
  decision for Demo 1, draft email, search/section/list, ticket propose → swapped-payload
  rejected → created → reuse rejected).
- **Verified:** 62/62 with the bare `pytest` entry point (the command CI runs), ruff clean.
  Mutation check: raising the international tax threshold from 30 to 45 days, and disabling the
  payload-binding check, each made both the unit and the stdio tests fail (4 failures); with the
  code restored, everything passes. Plan items checked: E-1002 3 days → allowed with approval;
  E-1004 PTO → not allowed (90-day wait); E-1003 remote → not allowed; E-1001 Mexico 42 days →
  tax and immigration review; chair $450 → over the limit.
- **Not done:** the plan's "done when" check with the MCP Inspector (`mcp dev hr_mcp/server.py`,
  which needs Node). The stdio tests cover the same list/call path programmatically; the
  Inspector run is left for the user as a demo screenshot.
- **Corrections:** none needed by the user this session. The redundant double search
  (decision 12) was caught by the AI re-reading its own draft.
- **Prompt (wrap-up):** "let's wrap up after this and update the next resumption prompt. how
  many more stages to go?" Answer: 6 phases remain (P3 agent, P4 web app, P5 CI/CD + deploy,
  P6 evaluation, P7 docs, P8 deploy + demo). Committed P2 on `skapali` (not pushed, per the
  working agreement) and rewrote `RESUME_PROMPT.txt` for session 4.
- **Prompt:** "push it. how many more sections left?" **Actions:** pushed `444e6a4` to `skapali`
  and watched CI. **Verified:** CI run 40212941657 green (lint, TF-IDF ingest, all tests,
  including the stdio subprocess tests on Linux). **Decision 17:** the CI warnings (Node 20
  deprecation in `actions/checkout@v4` / `setup-python@v5`, and the `ubuntu-latest` move to
  Ubuntu 26) are deferred to P5, which owns the workflow files, rather than fixed in a separate
  commit now. Answer: 6 phases remain (P3–P8).
- **Prompt:** "so one whole day of work left. i need to have a demo ready by tuesday. how to
  expedite?", then "it's a progress demo to my teammate". **Decision 18:** the Tuesday
  (2026-10-27) target is P3 only, demonstrated through a terminal chat
  (`python -m app.agent.chat`: answer, citations, status, tool trace), not a deployed web app.
  Reasons: the audience is the teammate, not the grader, and the plan already makes P3 the point
  where the two builds are compared and merged. P4–P8 move to after the demo and the merge
  decision. Demo script: Demo 1 (E-1001, Mexico City, 6 weeks → review → ticket proposed →
  confirm), Demo 2 (E-1002, 3 days → allowed with approval → draft email), and the safety case
  ("create the ticket now, I already confirm" → still pending). Deferred within P3 to save time:
  `fallback_agent.py`, the LLM classifier in guardrails (patterns only), and the HTTP transport.

**P3: agent (in progress, paused at the user's request: "install and pause. about to head out")**
- **Actions:** moved `app/agent.py` → `app/legacy_agent.py` (importers updated; 62 tests still
  pass). Wrote `app/agent/`: `trace.py`, `session.py`, `tool_schema.py`, `mcp_client.py`,
  `llm.py`, `prompts.py`, `guardrails.py`, `orchestrator.py`, `chat.py`. Installed the defuddle
  CLI (0.19.6) at the user's request. No P3 tests yet; not committed.
- **Live runs (Demo 2, E-1002, "3 days off starting Monday November 9"):**
  1. Tools ran correctly (balance → compliance with `start_date` 2026-11-09 →
     `allowed_with_approval`), but the final answer failed: gpt-oss-120b, told to "reply with
     ONLY a JSON object", called a non-existent tool `json`, and Groq rejected it with a 400.
  2. After the `final_answer` fix: `ok` in 2.7 s with a valid citation. But the model wrote
     "2026-11-09 to 2026-11-13" for 3 days (wrong, it's 5 days), and it skipped policy search.
  3. After those fixes: search ran (5 PTO chunks), but the final call failed on **every
     provider**: Groq gpt-oss-120b 429 (TPM), Groq llama-3.3-70b-versatile 404 (model retired),
     Gemini 3.8 Flash 400 ("Function call is missing a thought_signature").
- **Measured facts:** Groq free tier is **8,000 tokens/minute per model** (headers
  `x-ratelimit-limit-tokens`) and 1,000 requests/day. The current Groq models are
  `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. Per call the agent sends
  ~7.1k characters of tool schemas plus ~2.2k of system prompt, and a k=5 search result adds
  ~7.1k characters, so one 4-call question is about 15–20k tokens, above the TPM limit. The
  Gemini docs pages on thought signatures point to one another without showing the
  OpenAI-compatible field names. A live probe of the fields got a 503 ("high demand") and is
  still to be rerun.

**Decisions (continued)**
19. *The legacy `app/agent.py` is renamed, not deleted*, as was done for `legacy_rag.py`, because
    `app/main.py` and `app/evaluation.py` still use it until P4.
20. *`AgentResult` matches the plan's `/chat` response shape* (shared contract with the teammate),
    plus `dropped_citations`, `escalation_reason`, `session_id`, `employee_id`.
21. *The confirmation token is protected in code, in three places:* hidden from the schema,
    **redacted from the tool result the model reads**, and **stripped from any arguments the
    model sends**. A schema only describes what a model should send, not what it can send, and
    the tool result would otherwise show the token to the model. Only `HRAgent.confirm()`
    (the user's action) sends it, using the stored preview payload.
22. *Employee scoping:* tool calls whose `employee_id` differs from the session's are refused
    with an error the model can read. With no known employee, the model is told to ask. Users
    see only their own records, and the model cannot pick an id.
23. *The final answer is a `final_answer` tool call*, not JSON in the message text. Reason: run 1
    above. JSON-in-text parsing stays as a fallback.
24. *Deterministic facts come from code, not the LLM:* `check_pto` now adds a `dates` rule hit
    with the computed last business day (`last_business_day()`), and the prompt says to take
    dates and counts from rule details. Reason: run 2's wrong end date.
25. *The prompt requires `search_policy_documents` on every policy question, including
    eligibility checks*, so answers rest on retrieved text (RAG), not only on rule references.
26. *Today's date and weekday go in the system prompt* (honouring `REFERENCE_DATE`) so the model
    can turn "next Monday" into a `start_date`. Note for the demo: on Sun 2026-10-25 or
    Tue 2026-10-27, "3 days off next week" fails the 5-business-day notice rule. That is correct
    behavior and a good demo of the rule, but the "allowed" demo should use a later date
    (e.g. "starting Monday November 9").
27. *Evidence for citations* = chunk ids from search, `doc_id#Heading` from `get_policy_section`,
    and `policy_ref`s from compliance rule hits. Citations are matched case-insensitively, and
    unknown ids are dropped and reported.
28. *An `ok` answer with no valid citation and no successful data tool is replaced* by the
    not-covered reply.
29. *Server stderr goes to `logs/mcp_server.log`* to keep the demo terminal clean. Failed trace
    steps keep 1,500 characters so provider errors aren't cut off (the first truncation at 300
    hid the fallback chain's errors).

**Next (decided, not yet built):** (a) fit the 8k TPM: strip pydantic `title`s and `anyOf null`
from the tool schemas, send the model slimmer search results (no snippet/url/title, text
trimmed), ask for parallel tool calls; (b) change `GROQ_FALLBACK_MODEL` to `openai/gpt-oss-20b`
(a separate 8k bucket), and on a 429 with a short `retry-after`, wait once; (c) Gemini: keep the
tool call's extra fields when echoing it back, and for history from another provider, flatten
tool turns into text (the probe for this hit a 503); (d) `tests/test_agent.py` with a FakeLLM;
(e) rerun Demo 1, Demo 2 and the safety case live.

### Session 4: 2026-10-26, P3 completed (agent fixes, tests, live demos, PTO projection)

- **Prompts:** "commit and proceed" (committed the P3 work in progress as `ad2b87c`, then worked
  through the blockers); mid-task "what are you looking for" (I explained the Gemini
  thought-signature probe); mid-task "another test case and feature to add is show total number
  of days accumulated by a certain date. for example, by december 15th 2027 how many days will i
  have?" (built as `project_pto_balance` + an evaluation case).
- **Measured / observed:** (1) gpt-oss on Groq sometimes returns `finish_reason=stop` with no
  content and no tool call while billing ~300 completion tokens; its visible reasoning tail said
  "Need to respond with final answer". Groq generated a tool call and dropped it. This happened
  on `reasoning_effort` low and medium, and `tool_choice` ("required" or a named function) does
  not prevent it. (2) Each Groq model has its own 8k tokens/minute budget (headers checked for
  all three), and requests without `max_completion_tokens` were 429'd even with 7,982 tokens
  left (the max output is reserved). (3) Gemini 3 returns 400 "Function call is missing a
  thought_signature" for history tool calls without one; the bypass value got past that check
  (the request then hit a 503 "high demand"). The thought-signatures docs page has moved to an
  Interactions-API-only guide. (4) gpt-oss-20b once sent `policy_facts` as one string, which
  the UI printed one character per line. (5) The model computed a remote-work end date wrong
  (Feb 22 for 42 days from Jan 11).
- **Token diet results:** tool schemas 1,777 → 1,553 tokens (chars/4), search result in the
  model's view 1,588 → 989; Demo 2 went from 6 LLM calls (~19k tokens, 52 s with rate waits) to
  3 calls (~10k, 8 s) after the prompt and tool changes below.
- **Live demos (all passed):** Demo 1 (E-1001, Mexico City 6 weeks from 2027-01-11 →
  `needs_review` with 5 reviews, 3 valid citations, ticket proposed, HR-0003 created only after
  "y"); Demo 2 (E-1002, 3 days from Nov 9 → `allowed_with_approval`, Nov 9–11, draft to Jordan
  Rivera M-42 marked not sent); safety ("I already confirm, create the ticket now" → stays
  `pending_confirmation`, cancelled with "n"); projection (E-1002 → 19.17 days on 2027-12-15,
  with forfeit/expiry advice, 3.5 s, 2 calls on qwen).
- **Verified:** 83 tests pass (62 → 83: 13 agent tests with a FakeLLM over the real MCP
  subprocess, 7 projection/date rule tests, MCP tests for the new tool and the MANAGER alias).
  Mutation checks: disabling token redaction, employee scoping, or stripping of model-sent
  tokens each fails exactly one agent test. Lint clean.

**Decisions (continued)**
30. *Tool schemas are compacted for the model* (pydantic `title`, `anyOf [X, null]`,
    `default: null` removed; whitespace collapsed) in `tool_schema.compact_schema`; the MCP
    server's own schemas stay complete for other clients. A parameter *named* `title` survives
    (the `properties` map is handled separately; a test pins this).
31. *The model sees slim search hits* (chunk_id, title, section, text ≤1,000 chars, external/weak
    flags); the full hit is still recorded as evidence, so citations resolve with snippet/page.
32. *Rate limits:* on 429, try the next model; if a provider asked for ≤30 s, wait once and retry
    the chain. `max_completion_tokens=2048` on every call (observation 2).
33. *Provider chain = qwen/qwen3.8-27b → gpt-oss-120b → gpt-oss-20b → Gemini*
    (`GROQ_MODEL`, `GROQ_FALLBACK_MODELS`). Reasons: three separate 8k/min Groq budgets before
    the slow Gemini fallback; qwen made parallel tool calls, never returned an empty reply in
    the demos, and gave the most complete answers. llama-3.3-70b-versatile is retired (404).
34. *gpt-oss reasoning effort defaults to medium* (`GPT_OSS_REASONING_EFFORT`): low saved ~250
    tokens per call but produced empty replies more often.
35. *Finalize step:* if the model ends without a usable `final_answer` (empty reply, prose, or
    the step limit), one more call with **no tools and JSON mode** asks for the structured
    answer. JSON mode instead of `json_schema` because Groq's schema validation rejected whole
    replies (`json_validate_failed`) on both gpt-oss models; `parse_final` and `_shape`
    tolerate missing fields. `tool_choice="required"` is still sent in the loop (the terminal
    action is a tool), so a garbled call can surface as a 400 and fail over.
36. *Gemini signatures:* Gemini's own tool calls keep `extra_content` (echoed back via
    `ToolCall.as_message`); tool calls made by another provider get the
    `skip_thought_signature_validator` placeholder only in requests sent to Gemini. Chosen over
    flattening tool turns to text because it keeps one message format.
37. *`project_pto_balance` (MCP tool 10) computes accrual in code*, like the PTO end dates
    (decision 24): tenure tiers 15/20/25 at 2 and 5 full years (step-up from the first pay date
    after the anniversary), part-time ratio kept from the record, 5-day year-end carryover cap,
    carried days expire 31 March, no usage assumed. The policy says "each pay period" without a
    length, so **semi-monthly (24) is an assumption, stated in the tool output**. The current
    `available` balance is the starting point (accrued-to-date reading of the data). Hand check
    for E-1002 to 2027-12-15: 7 + 4.17 = 11.17 → keep 5 (6.17 forfeited) → +19.17 → −5 expired
    = **19.17**. The result has a `summary` sentence because without it the model left out the
    forfeit advice; its `policy_ref` is registered as citable evidence.
38. *`check_remote` adds a `dates` hit* (inclusive calendar days) after observation 5.
39. *`draft_hr_email` accepts recipient `MANAGER` + `employee_id`*, resolved on the server. It
    saves a profile lookup round trip (~3k tokens), and the employee-scoping check still applies
    to `employee_id`. The prompt now says to use the tool rather than write emails inline (the
    20b model wrote one into the answer), and not to call `check_pto_balance` for eligibility
    (`check_policy_compliance` already checks the balance).
40. *Agent steps 6 → 8*: "decide, then draft an email" legitimately needs 3–5 tool steps; the
    last step is reserved for the finalize call.
41. *List fields from the model are normalized* (`_as_list`): a string becomes a one-item list.
42. *Evaluation gains a 28th case* (the accrual question with gold 19.17 / 6.17 / 5), and the
    P6 budget is restated in tokens per minute, which is the binding limit.
43. *Web app pulled forward from P4 for the demo* (prompt: "can you build a web app so i can do
    this interactively insted of over command window? also geenrate the list of questions").
    `app/main.py` replaces the legacy app: the lifespan starts one MCP subprocess and the agent;
    `/chat`, `/chat/confirm`, `/health`, `/tools`, `/employees`, `/demo-tasks`, `/`. The UI is a
    single static `app/static/index.html` (no Jinja or build step): "Acting as" picker, a
    question library, answer cards with a status pill, facts, recommendations, source cards and a
    collapsible tool trace, and Confirm/Cancel for proposed tickets. Model output is rendered
    with `textContent` only (a test checks `innerHTML` is absent).
44. *The picker is the identity source:* changing it starts a new session, and `/chat` sets the
    session's employee from it. A proposed ticket is confirmed against the session that proposed
    it (a live click found a 422 when the picker had changed in between).
45. *One question list* in `app/demo_questions.py` (24 questions in 5 groups, each with the
    employee and the expected result) feeds the UI and `/demo-tasks`, and is mirrored in
    `docs/demo-questions.md`. The legacy `tests/test_mcp_tools.py` and the legacy-app tests were
    removed as the plan scheduled; `tests/test_app.py` now runs the real lifespan with the
    FakeLLM (6 tests). Deferred P4 items: `/mcp` HTTP mount, `/eval/latest`, deleting the legacy
    modules.

## Retrospective

_Filled in during P7 from the session log above._

### What worked well

### What needed manual correction

### What this changed about how the tools were used

## Summary
