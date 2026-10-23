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

## Retrospective

_Filled in during P7 from the session log above._

### What worked well

### What needed manual correction

### What this changed about how the tools were used

## Summary
