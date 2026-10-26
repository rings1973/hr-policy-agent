"""Convert MCP tool definitions into OpenAI-style function tools for the LLM.

Parameters in HIDDEN_PARAMS are removed, so the model cannot even express them. The ticket
`confirmation_token` is only ever sent by the application after the user clicks confirm.
"""

from __future__ import annotations

import copy
from typing import Any

HIDDEN_PARAMS = frozenset({"confirmation_token"})


def to_openai_tools(tools: list[Any], hidden: frozenset[str] = HIDDEN_PARAMS) -> list[dict]:
    converted = []
    for tool in tools:
        schema = copy.deepcopy(tool.input_schema) or {"type": "object", "properties": {}}
        schema.pop("title", None)
        props = schema.get("properties", {})
        for name in hidden:
            props.pop(name, None)
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r not in hidden]
        converted.append({"type": "function", "function": {
            "name": tool.name, "description": tool.description or "", "parameters": schema}})
    return converted
