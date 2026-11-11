"""LLM judge for groundedness and answer correctness.

The judge is Gemini, a different model family from the Groq models that generate answers, so a
model does not grade its own output. One call per case returns both scores as JSON:
  - groundedness: the answer is split into factual claims, each checked against the evidence
    (retrieved chunk text and tool result summaries); score = supported / total claims.
  - correctness: each gold fact is marked covered or not; score = covered / total gold facts.
When no key is set or the call fails, run_eval falls back to the lexical metrics.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import openai

from app import config
from app.agent.llm import GEMINI_URL

RATE_RETRIES, RATE_WAIT_S = 3, 20.0

PROMPT = """You grade an HR assistant's answer. Reply with JSON only.

EVIDENCE (the only text the assistant was allowed to rely on):
<<<
{evidence}
>>>

ANSWER:
<<<
{answer}
>>>

GOLD FACTS (what a correct answer states):
{facts}

Tasks:
1. Split the ANSWER into its distinct factual claims about policy, dates, numbers, eligibility or
   records (skip greetings, offers to help and advice to contact HR). For each claim, set
   "supported" to true only if the EVIDENCE states or directly implies it.
2. For each GOLD FACT, set "covered" to true if the ANSWER states it (wording may differ; numbers
   and dates must match).

JSON shape:
{{"claims": [{{"claim": "...", "supported": true}}],
  "facts": [{{"fact": "...", "covered": true}}]}}"""


class Judge:
    def __init__(self, model: str = config.JUDGE_MODEL) -> None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=config.GEMINI_API_KEY, base_url=GEMINI_URL,
                                         max_retries=2, timeout=60)

    async def grade(self, answer: str, evidence: str, gold_facts: list[str]) -> dict[str, Any]:
        facts = "\n".join(f"- {f}" for f in gold_facts) or "(none)"
        messages = [{"role": "user", "content": PROMPT.format(
            evidence=evidence[:12000] or "(no evidence retrieved)", answer=answer, facts=facts)}]
        for attempt in range(RATE_RETRIES + 1):
            try:
                reply = await self.client.chat.completions.create(
                    model=self.model, temperature=0, response_format={"type": "json_object"},
                    messages=messages)
                break
            except openai.RateLimitError:
                # Free tier: 5 requests/minute for this model, so wait out the window.
                if attempt == RATE_RETRIES:
                    raise
                await asyncio.sleep(RATE_WAIT_S)
        claims, covered = parse_verdict(json.loads(reply.choices[0].message.content or "{}"))
        return {
            "groundedness": round(sum(bool(c.get("supported")) for c in claims) / len(claims), 3)
            if claims else None,
            # A judge that lists a fact twice must not push the score above 1.
            "correctness": round(min(1.0, sum(bool(f.get("covered")) for f in covered)
                                     / len(gold_facts)), 3) if gold_facts else None,
            "claims": claims,
            "facts": covered,
            "model": self.model,
        }


def parse_verdict(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the judge's claims and facts from the shapes models actually return.

    JSON mode guarantees valid JSON, not the requested shape: the object may come wrapped in a
    list, split across several objects, or as a bare list of claims. Entries that are not
    objects are ignored."""
    if isinstance(data, dict):
        parts = [data]
    elif isinstance(data, list):
        parts = [p for p in data if isinstance(p, dict)]
        if parts and not any("claims" in p or "facts" in p for p in parts):
            parts = [{"claims": [p for p in parts if "supported" in p],
                      "facts": [p for p in parts if "covered" in p]}]
    else:
        parts = []
    claims: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for part in parts:
        claims += [c for c in part.get("claims") or [] if isinstance(c, dict)]
        facts += [f for f in part.get("facts") or [] if isinstance(f, dict)]
    return claims, facts
