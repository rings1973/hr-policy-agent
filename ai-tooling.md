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

## Retrospective

_Filled in during P7 from the session log above._

### What worked well

### What needed manual correction

### What this changed about how the tools were used

## Summary
