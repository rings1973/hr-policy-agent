"""Chat-completion client over OpenAI-compatible endpoints, with provider fallback.

Providers are tried in order (config.LLM_PROVIDERS, default groq then gemini); each Groq model is
its own attempt. Any API error, timeout or rate limit moves on to the next one. Every call has a
hard timeout and no SDK retries, so a slow provider costs at most `timeout` seconds before the
fallback runs (Gemini chat was measured at ~63 s or 503 on 2026-10-23).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from app import config

GROQ_URL = "https://api.groq.com/openai/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MAX_RATE_WAIT = 30.0  # seconds; longer 429 waits (daily limits) fail over instead
# Reasoning + a full final_answer fit in ~1.5k. Without a cap the request is checked against the
# per-minute token limit with the model's maximum output reserved (qwen 429'd at 7982 left).
MAX_COMPLETION_TOKENS = 2048


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text from the model; parsed (and possibly rejected) by the caller
    extra: dict[str, Any] | None = None  # provider fields to echo back (Gemini thought_signature)

    def as_message(self) -> dict[str, Any]:
        """The OpenAI-format tool_call entry for the assistant turn in history."""
        msg: dict[str, Any] = {"id": self.id, "type": "function",
                               "function": {"name": self.name, "arguments": self.arguments}}
        return {**msg, **(self.extra or {})}


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens: int = 0  # prompt + completion, as billed against the provider's per-minute limit
    finish_reason: str = ""


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict],
                   answer_schema: dict[str, Any] | None = None) -> LLMReply: ...


class LLMUnavailable(RuntimeError):
    """Every configured provider failed or none is configured."""


@dataclass
class Provider:
    name: str
    model: str
    client: openai.AsyncOpenAI
    supports_seed: bool


def configured_providers(timeout: float = 20.0) -> list[Provider]:
    providers: list[Provider] = []
    for name in config.LLM_PROVIDERS:
        if name == "groq" and config.GROQ_API_KEY:
            client = openai.AsyncOpenAI(api_key=config.GROQ_API_KEY, base_url=GROQ_URL,
                                        timeout=timeout, max_retries=0)
            for model in dict.fromkeys([config.GROQ_MODEL, *config.GROQ_FALLBACK_MODELS]):
                if model:
                    providers.append(Provider("groq", model, client, supports_seed=True))
        elif name == "gemini" and config.GEMINI_API_KEY:
            client = openai.AsyncOpenAI(api_key=config.GEMINI_API_KEY, base_url=GEMINI_URL,
                                        timeout=timeout, max_retries=0)
            providers.append(Provider("gemini", config.GEMINI_MODEL, client, supports_seed=False))
    return providers


class LLMClient:
    def __init__(self, providers: list[Provider] | None = None) -> None:
        self.providers = configured_providers() if providers is None else providers
        self.errors: list[str] = []  # failures from the most recent chat() call

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict],
                   answer_schema: dict[str, Any] | None = None) -> LLMReply:
        """With `answer_schema`, no tools are offered and the reply content is JSON constrained
        to that schema (response_format json_schema)."""
        self.errors = []
        if not self.providers:
            raise LLMUnavailable("No LLM provider configured (set GROQ_API_KEY or GEMINI_API_KEY).")
        for attempt in range(2):
            waits: list[float] = []
            for p in self.providers:
                try:
                    return await self._call(p, messages, tools, answer_schema)
                except openai.RateLimitError as exc:
                    waits.append(retry_after(exc))
                    self.errors.append(f"{p.name}/{p.model}: rate limited ({waits[-1]:.0f}s)")
                except openai.APIError as exc:
                    self.errors.append(
                        f"{p.name}/{p.model}: {type(exc).__name__}: {str(exc)[:200]}")
            # Per-minute token limits reset quickly: if any provider asked for a short wait,
            # waiting once beats returning "unavailable" for a question that fits after a pause.
            wait = min(waits, default=MAX_RATE_WAIT + 1)
            if attempt or wait > MAX_RATE_WAIT:
                break
            await asyncio.sleep(wait)
        raise LLMUnavailable("All LLM providers failed: " + " | ".join(self.errors))

    @staticmethod
    async def _call(p: Provider, messages: list[dict[str, Any]], tools: list[dict],
                    answer_schema: dict[str, Any] | None) -> LLMReply:
        extra: dict[str, Any] = {"seed": config.SEED} if p.supports_seed else {}
        if answer_schema:
            # JSON mode, not json_schema: Groq's schema validation rejected whole replies
            # (json_validate_failed, e.g. a null optional field) on both gpt-oss models. The
            # caller tolerates missing fields; the schema is described in the instruction.
            tools = []
            extra["response_format"] = {"type": "json_object"}
        elif tools:
            # The loop's terminal action is the final_answer tool, so every reply must be a tool
            # call. Without this, gpt-oss on Groq sometimes returned an empty reply (a generated
            # call the provider failed to parse); "required" turns that into a 400, which fails
            # over to the next model instead of silently ending the turn.
            extra["tool_choice"] = "required"
        if p.model.startswith("openai/gpt-oss") and config.GPT_OSS_REASONING_EFFORT:
            extra["reasoning_effort"] = config.GPT_OSS_REASONING_EFFORT
        if p.name == "gemini":
            messages = with_gemini_signatures(messages)
        resp = await p.client.chat.completions.create(
            model=p.model, messages=messages, tools=tools or openai.omit,
            temperature=0, max_completion_tokens=MAX_COMPLETION_TOKENS, **extra)
        msg = resp.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}",
                          {"extra_content": c.extra_content}
                          if getattr(c, "extra_content", None) else None)
                 for c in (msg.tool_calls or [])]
        return LLMReply(msg.content or "", calls, p.name, p.model,
                        resp.usage.total_tokens if resp.usage else 0,
                        resp.choices[0].finish_reason or "")


SKIP_SIGNATURE = "skip_thought_signature_validator"


def with_gemini_signatures(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gemini 3 rejects (400) history tool calls without a thought_signature. Its own calls carry
    one in extra_content; calls made by another provider before a fallback get Google's
    documented placeholder so the conversation can continue on Gemini."""
    out = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = {**m, "tool_calls": [
                c if c.get("extra_content", {}).get("google", {}).get("thought_signature")
                else {**c, "extra_content": {"google": {"thought_signature": SKIP_SIGNATURE}}}
                for c in m["tool_calls"]]}
        out.append(m)
    return out


def retry_after(exc: openai.APIStatusError) -> float:
    """Seconds the provider asks us to wait; Groq sends retry-after on 429 (e.g. "7.66")."""
    try:
        return float(exc.response.headers.get("retry-after", MAX_RATE_WAIT + 1))
    except (TypeError, ValueError):
        return MAX_RATE_WAIT + 1
