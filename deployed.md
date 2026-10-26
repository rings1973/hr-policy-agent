# Deployment

> _TODO (P8): fill in the URLs and measured numbers after the first deploy from `main`._

| | |
|---|---|
| App | `https://<service>.onrender.com/` |
| Health | `https://<service>.onrender.com/health` (expect `mcp.connected: true`, `tool_count: 10`) |
| Tools | `https://<service>.onrender.com/tools` |
| Latest evaluation | `https://<service>.onrender.com/eval/latest` |
| Host | Render free web service, Python 3.13, region _TBD_ |
| Deploys | Only from the CI `deploy` job on `main`, after all tests pass (`render.yaml` sets `autoDeployTrigger: off`) |

## Configuration

Set in the Render dashboard (never in the repo): `GROQ_API_KEY`, `GEMINI_API_KEY`.
Set by `render.yaml`: `PYTHON_VERSION=3.13.11`, `EMBEDDING_BACKEND=gemini`, `APP_ENV=production`.
The build runs `python -m app.rag.ingest --embedder all`, so the keyless TF-IDF index always
exists as a fallback if the Gemini embedding call fails at build time.

## Cold start

Render's free tier stops the instance after 15 minutes without traffic. Measured with
`python -m evaluation.latency_probe <url> --rounds 3 --idle-minutes 16`:

| Measure | Value |
|---|---|
| First `/health` after idle (cold), p50 / max | _TBD_ |
| First `/chat` after the cold start | _TBD_ |
| Warm `/health` p50 | _TBD_ |
| Memory in use (Render metrics) | _TBD_ (budget estimate ≈ 220 MB of 512 MB) |

Before a demo or recording, open `/health` about 2 minutes ahead so the instance is warm.

## Free-tier limits that affect the app

- Groq: ~8,000 tokens per minute per model; one question costs ~5–10k tokens, so the app spreads
  load across three Groq models before Gemini.
- Gemini 3.8 Flash: 20 requests per day on the free tier (last-resort LLM only).
- Sessions and proposed tickets are in memory and reset when the instance sleeps.
