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
        data = json.loads(reply.choices[0].message.content or "{}")
        claims, covered = data.get("claims", []), data.get("facts", [])
        return {
            "groundedness": round(sum(bool(c.get("supported")) for c in claims) / len(claims), 3)
            if claims else None,
            "correctness": round(sum(bool(f.get("covered")) for f in covered) / len(gold_facts), 3)
            if gold_facts else None,
            "claims": claims,
            "facts": covered,
            "model": self.model,
        }
