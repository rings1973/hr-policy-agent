"""Chat-completion client over OpenAI-compatible endpoints, with provider fallback.

Providers are tried in order (config.LLM_PROVIDERS, default groq then gemini); each Groq model is
its own attempt. Any API error, timeout or rate limit moves on to the next one. Every call has a
hard timeout and no SDK retries, so a slow provider costs at most `timeout` seconds before the
fallback runs (Gemini chat was measured at ~63 s or 503 on 2026-10-23).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from app import config

GROQ_URL = "https://api.groq.com/openai/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text from the model; parsed (and possibly rejected) by the caller


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict]) -> LLMReply: ...


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
            for model in dict.fromkeys([config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL]):
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

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict]) -> LLMReply:
        self.errors = []
        if not self.providers:
            raise LLMUnavailable("No LLM provider configured (set GROQ_API_KEY or GEMINI_API_KEY).")
        for p in self.providers:
            extra = {"seed": config.SEED} if p.supports_seed else {}
            try:
                resp = await p.client.chat.completions.create(
                    model=p.model, messages=messages, tools=tools or openai.omit,
                    temperature=0, **extra)
            except openai.APIError as exc:
                self.errors.append(f"{p.name}/{p.model}: {type(exc).__name__}: {str(exc)[:200]}")
                continue
            msg = resp.choices[0].message
            calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}")
                     for c in (msg.tool_calls or [])]
            return LLMReply(msg.content or "", calls, p.name, p.model)
        raise LLMUnavailable("All LLM providers failed: " + " | ".join(self.errors))
