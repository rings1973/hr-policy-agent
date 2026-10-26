"""Convert MCP tool definitions into OpenAI-style function tools for the LLM.

Parameters in HIDDEN_PARAMS are removed, so the model cannot even express them. The ticket
`confirmation_token` is only ever sent by the application after the user clicks confirm.

Schemas are also compacted: pydantic's titles, `anyOf [X, null]` and `default: null` are noise to
the model (a field not in `required` is already optional) and cost ~40% of the schema tokens,
which are resent on every step under Groq's 8k tokens/minute free tier.
"""

from __future__ import annotations

import copy
import re
from typing import Any

HIDDEN_PARAMS = frozenset({"confirmation_token"})


def compact_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [compact_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    node = {k: v for k, v in node.items() if k != "title" and not (k == "default" and v is None)}
    variants = node.get("anyOf")
    if isinstance(variants, list):
        non_null = [v for v in variants if v != {"type": "null"}]
        if len(non_null) == 1 and len(non_null) < len(variants):
            node.pop("anyOf")
            node = {**non_null[0], **node}
    if isinstance(node.get("description"), str):
        node["description"] = re.sub(r"\s+", " ", node["description"]).strip()
    if isinstance(node.get("properties"), dict):  # a name -> schema map, not a schema itself
        node["properties"] = {name: compact_schema(s) for name, s in node["properties"].items()}
    for key in ("items", "anyOf"):
        if key in node:
            node[key] = compact_schema(node[key])
    return node


def to_openai_tools(tools: list[Any], hidden: frozenset[str] = HIDDEN_PARAMS) -> list[dict]:
    converted = []
    for tool in tools:
        schema = compact_schema(copy.deepcopy(tool.input_schema)
                                or {"type": "object", "properties": {}})
        props = schema.get("properties", {})
        for name in hidden:
            props.pop(name, None)
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r not in hidden]
        converted.append({"type": "function", "function": {
            "name": tool.name, "description": re.sub(r"\s+", " ", tool.description or "").strip(),
            "parameters": schema}})
    return converted
