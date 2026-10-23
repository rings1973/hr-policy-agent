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

## Retrospective

_Filled in during P7 from the session log above._

### What worked well

### What needed manual correction

### What this changed about how the tools were used

## Summary
