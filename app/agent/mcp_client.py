"""Async client for the hr_mcp server, launched as a stdio subprocess.

    client = MCPToolClient()
    await client.start()
    result = await client.call_tool("lookup_employee_profile", {"employee_id": "E-1001"})
    await client.aclose()

start() and aclose() must run in the same task (anyio cancel-scope rule), which holds for a CLI
loop and for a FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, TextIO

import anyio
from mcp import StdioServerParameters
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from app import config

SERVER_LOG = config.BASE_DIR / "logs" / "mcp_server.log"


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] | None
    error: str | None
    latency_ms: int


class MCPToolClient:
    def __init__(self, env: dict[str, str] | None = None, timeout: float = 20.0) -> None:
        self.params = StdioServerParameters(
            command=sys.executable, args=["-m", "hr_mcp.server"],
            env={**os.environ, **(env or {})}, cwd=str(config.BASE_DIR))
        self.timeout = timeout
        self.session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._tools: list[Any] | None = None
        self._lock = asyncio.Lock()
        self._errlog: TextIO | None = None

    @property
    def connected(self) -> bool:
        return self.session is not None

    async def start(self) -> None:
        stack = AsyncExitStack()
        try:
            SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
            self._errlog = stack.enter_context(SERVER_LOG.open("a", encoding="utf-8"))
            read, write = await stack.enter_async_context(stdio_client(self.params, self._errlog))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self.session = stack, session

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self.session = None

    async def list_tools(self) -> list[Any]:
        if self._tools is None:
            async with self._lock:
                self._tools = (await self._require().list_tools()).tools
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool; a dead server gets one restart. Tool errors come back as ok=False."""
        start = time.perf_counter()
        async with self._lock:
            try:
                result = await self._call(name, arguments)
            except (OSError, EOFError, anyio.ClosedResourceError, anyio.BrokenResourceError,
                    anyio.EndOfStream):
                await self.aclose()
                await self.start()
                result = await self._call(name, arguments)
        latency = int((time.perf_counter() - start) * 1000)
        text = " ".join(getattr(c, "text", "") for c in result.content).strip()
        if result.is_error:
            return ToolResult(False, None, text or f"{name} failed", latency)
        return ToolResult(True, result.structured_content or {"text": text}, None, latency)

    async def _call(self, name: str, arguments: dict[str, Any]):
        return await self._require().call_tool(name, arguments, read_timeout_seconds=self.timeout)

    def _require(self) -> ClientSession:
        if self.session is None:
            raise RuntimeError("MCP client is not started")
        return self.session
