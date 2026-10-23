# References

These are the external sources behind this project's design choices and corpus, grouped by the rubric section
they support. Retrieved 2026-10-22. Free-tier limits change often, so recheck the provider pages before quoting
numbers in the demo.

Legend: ✅ official or primary source, link checked 2026-10-22 (HTTP 200) · ⚠️ third-party source or unconfirmed figure, check before citing.

## Assignment
- Project brief and rubric: `MSAIEProject3.pdf` (Quantic, *AI Engineering Techniques and Architectures Project*). Not committed.

## §2 Corpus: policy documents and licenses
Used in the corpus (see `app/data/policies/SOURCES.md`):
- ✅ NIST SP 800-46 Rev. 2, *Guide to Enterprise Telework, Remote Access, and BYOD Security* (PDF): https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-46r2.pdf
- ✅ NIST copyright and attribution policy: https://www.nist.gov/oism/copyrights
- ✅ OPM *Fact Sheet: Annual Leave* (HTML): https://www.opm.gov/policy-data-oversight/pay-leave/leave-administration/fact-sheets/annual-leave/
- ✅ OPM leave fact sheets index: https://www.opm.gov/policy-data-oversight/pay-leave/leave-administration/fact-sheets/
- ✅ U.S. Government works are not copyrighted (17 U.S.C. §105): https://www.usa.gov/government-copyright

Other open-licensed handbooks (evaluated, not used):
- ✅ GitLab Handbook, MIT license: https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/ · license: https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/main/LICENSE
- ✅ PostHog Handbook. Only the `/contents/` folder is MIT: https://raw.githubusercontent.com/PostHog/posthog.com/master/LICENSE
- ✅ Clef Handbook, CC0-1.0: https://github.com/clef/handbook
- ✅ OPM Sample Situational Telework Agreement (PDF): https://www.opm.gov/telework/sample-situational-telework-agreement.pdf
- ✅ GSA Federal Travel Regulation, 41 CFR (PDF): https://www.govinfo.gov/content/pkg/CFR-2021-title41-vol4/pdf/CFR-2021-title41-vol4.pdf
- ⚠️ Sourcegraph Handbook, Apache-2.0, archived: https://github.com/sourcegraph/handbook
- ⚠️ awesome-handbooks list: https://www.context-awesome.com/list/hkdobrev/awesome-handbooks
- ⚠️ Hugging Face HR policy dataset, Apache-2.0, synthetic: https://huggingface.co/datasets/adarsh-08/hr-policy-dataset

Excluded because of their licenses:
- ✅ SANS terms forbid redistribution and AI upload: https://www.sans.org/legal/terms-conditions
- ✅ Basecamp handbook has no license file: <https://github.com/basecamp/handbook>
- ✅ Basecamp's CC BY license covers only the `basecamp/policies` repo: https://signalvnoise.com/svn3/all-basecamp-policies-are-now-on-github-and-licensed-under-creative-commons

## §2 Vector store options
- ✅ FAISS (chosen): https://github.com/facebookresearch/faiss
- ✅ Chroma: https://docs.trychroma.com/
- ✅ LanceDB: https://lancedb.github.io/lancedb/
- ✅ Qdrant pricing and free tier comparison: https://qdrant.tech/pricing/comparison/
- ⚠️ Qdrant Cloud free tier idle suspension (third-party guide): https://glama.ai/mcp/servers/@NgoTaiCo/mcp-codebase-index/blob/341495a9fd820073fa3a658772b5d664f2af5983/docs/guides/QDRANT_CLOUD_SETUP.md
- ✅ Pinecone pricing (Starter): https://pinecone.io/pricing/
- ✅ Weaviate sandbox expiry FAQ: https://docs.weaviate.io/cloud/faq
- ✅ sqlite-vec: https://github.com/asg017/sqlite-vec
- ✅ pgvector: https://github.com/pgvector/pgvector

## §2 Embedding models
- ✅ Gemini embedding model (`gemini-embedding-001`): https://developers.googleblog.com/gemini-embedding-available-gemini-api/
- ✅ FastEmbed (ONNX, local): https://github.com/qdrant/fastembed
- ✅ BAAI/bge-small-en-v1.5: https://huggingface.co/BAAI/bge-small-en-v1.5
- ⚠️ Embedding API pricing comparison (third-party): https://www.costbench.com/software/embedding-apis/compare-all/
- ⚠️ fastembed vs sentence-transformers memory benchmark (third-party): https://pypi.org/project/ggmbed/

## LLM providers
- ✅ Groq rate limits (primary LLM): https://console.groq.com/docs/rate-limits
- ✅ Groq OpenAI-compatible API: https://console.groq.com/docs/openai
- ⚠️ Groq pricing summary (third-party): https://eesel.ai/blog/groq-pricing
- ✅ Gemini API rate limits (fallback LLM; actual quotas are shown in AI Studio): https://ai.google.dev/gemini-api/docs/rate-limits
- ✅ Gemini OpenAI-compatible endpoint: https://ai.google.dev/gemini-api/docs/openai
- ✅ Google AI Studio get-started (names `gemini-3.8-flash` as the default model; checked 2026-10-23, when `gemini-2.5-flash` returned 404 "no longer available to new users"): https://aistudio.google.com/docs/get-started
- ⚠️ Gemini free-tier changes (third-party): https://agentdeals.dev/gemini-api-pricing-changes
- ⚠️ OpenRouter free-tier limits (third-party): https://www.truefoundry.com/fr/blog/openrouter-rate-limits-your-free-tier-depends-on-what-youve-already-paid
- ⚠️ Cerebras free plan (third-party): https://costbench.com/software/llm-api-providers/cerebras-inference/free-plan/
- ⚠️ Mistral pricing, including the free Experiment plan (the original help-center article now returns 404): https://mistral.ai/pricing

## §5 Model Context Protocol
- ✅ MCP Python SDK on PyPI (v2.3.0 pinned): https://pypi.org/project/mcp/
- ✅ MCP Python SDK v2 migration guide (`FastMCP` → `MCPServer`, `streamable_http_client`): https://py.sdk.modelcontextprotocol.io/v2/migration/
- ✅ MCP Python SDK repository: https://github.com/modelcontextprotocol/python-sdk
- ✅ MCP specification (transports: stdio, Streamable HTTP): https://modelcontextprotocol.io/specification
- ✅ MCP Inspector: https://github.com/modelcontextprotocol/inspector

## §7–8 Deployment and CI/CD
- ✅ Render free tier (512 MB, spin-down after 15 min idle): https://render.com/docs/free
- ✅ Render deploys, auto-deploy, and deploy hooks: https://render.com/docs/deploys
- ✅ Render "auto-deploy only after CI checks pass": https://render.com/changelog/skip-auto-deploying-if-ci-checks-fail
- ✅ Render Blueprint (`render.yaml`) spec: https://render.com/docs/blueprint-spec
- ✅ GitHub Actions workflow syntax: https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions
