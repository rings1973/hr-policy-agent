# Retrieval calibration notes (P1, 2026-10-23)

Raw evidence for `design-and-evaluation.md` (P7) and the embedder ablation (P6).
Index: 137 chunks from 12 documents (md, txt, pdf, html), heading-aware, 350 words max with 60 words of overlap.

## TF-IDF vs Gemini `gemini-embedding-001` (768 dims): top 3 hits

Scores are cosine similarity. Each cell shows `doc/section=score`.

| Query type | Query | TF-IDF top hit | Gemini top 3 |
|---|---|---|---|
| direct | How many PTO days do I get after 5 years? | pto/Annual PTO Entitlement 0.32 ✅ | pto/Annual PTO Entitlement 0.76 ✅, **opm/Overview 0.68** ⚠️ external, pto/Planning 0.67 |
| direct | Reimbursement limit for an office chair? | expense/Equipment and Office 0.25 ✅ | expense/Reimbursement Limits 0.77 ✅ |
| paraphrase | Can I do my job from another country for a while? | remote/Tax and Location 0.15 ✅ (weak margin) | remote/International Work 0.74 ✅ |
| paraphrase | I want to take a vacation next week, who do I tell? | opm/Annual Leave While… 0.10 ❌ | pto/Planning and Submitting 0.73 ✅, pto/Notice and Approval 0.72 ✅ |
| paraphrase | my boss keeps making inappropriate jokes | holiday/Holiday and PTO 0.11 ❌ | workplace_conduct/Purpose 0.61 ✅ |
| multi-doc | work from another state: tax and security rules | remote/Tax and Location 0.27 (one doc only) | remote/Tax 0.71, **data_security/Remote Work Security 0.69**, remote/Security 0.69 ✅ two docs |
| off-topic | Current stock price of the company? | expense 0.14 | nist/Page 2 0.53 |
| off-topic | Write me a poem about the ocean | workplace_conduct 0.21 | holiday 0.50 |
| gibberish | zxqv blorf wuggle | 0.00 | holiday 0.59 |

## Findings

1. **Paraphrases.** TF-IDF only matches shared words. The PTO policy never says "vacation" or
   "tell", so TF-IDF missed it completely, while Gemini ranked the right two sections first.
   This is the case for dense embeddings.
2. **Dense scores are compressed.** For Gemini, relevant top hits scored 0.61–0.77, while
   off-topic and nonsense queries scored 0.50–0.59, and the nonsense query beat both real
   off-topic ones. The plan's flat `MIN_SCORE=0.30` would never mark anything as weak. The
   threshold is now stored per embedder in `manifest.json`: **gemini 0.60, tfidf 0.10**. It can
   be overridden with `MIN_SCORE` in `.env`.
3. **The margin is thin (0.59 vs 0.61).** The score threshold is therefore one safety layer, not
   the guardrail. Off-topic detection also happens in `guardrails.pre_route` (P3), and the LLM
   must answer "not covered" when the retrieved text doesn't support an answer.
4. **External references rank highly.** The OPM federal fact sheet came second for a company PTO
   question. Every chunk therefore carries `source_type`, and the P3 prompt treats
   `external_reference` chunks as background only. `search(source_type=...)` can exclude them.
5. **TF-IDF thresholds don't separate.** The poem scored 0.21, higher than the correct
   "another country" hit at 0.15. TF-IDF remains as the keyless CI and fallback baseline only.

6. **A question the policies don't answer can still score above the cutoff.** "Do we get free
   lunch?" got 0.616 from Gemini (expense_policy > Meals, Meetings, and Representation), which is
   above the 0.60 cutoff, so it was not flagged weak. The topic is close, but the section doesn't
   answer the question. The score measures how close the topic is, not whether the question is
   answered, so the P3 LLM must decide whether the retrieved text actually answers it.

## Try it

`python -m app.rag.explore` opens an interactive search showing both embedders side by side.
`python -m app.rag.explore --help` lists the options.

## Operational notes

- Gemini free tier: `embed_content` is limited to **100 texts per minute per model**, and each
  text in a batch counts separately. Ingest paces requests to 90 texts a minute and waits for
  the server's `retryDelay` on a 429. A full build of 137 chunks takes about 96 s.
- If Gemini is missing or fails during a build, ingest builds TF-IDF instead, and `open_index`
  falls back to it at runtime.

To revisit in P6: re-check the 0.60 threshold against the 26 eval cases, comparing
hit@k and MRR for each embedder and k ∈ {2, 4, 8}.
