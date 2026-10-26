"""Talk to the agent in the terminal, with citations, status and the tool trace.

    python -m app.agent.chat                                  interactive
    python -m app.agent.chat --employee E-1001
    python -m app.agent.chat --employee E-1002 "Can I take 3 days off next week?"

Interactive commands: :as E-1002 (act as an employee)   :trace (toggle trace)   :q
A proposed ticket asks for confirmation here: that answer is the user's click, not the model's.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap

from app.agent import AgentResult, HRAgent, LLMClient, MCPToolClient, Session

WIDTH = 96


def wrap(text: str, indent: str = "  ") -> str:
    return textwrap.indent(textwrap.fill(text, width=WIDTH - len(indent)), indent)


def show(result: AgentResult, trace: bool) -> None:
    print(f"\n[{result.status}]  {result.latency_ms / 1000:.1f}s  {result.provider or ''}")
    print(wrap(result.answer))
    for title, items in (("Policy facts", result.policy_facts),
                         ("Recommendations", result.recommendations)):
        if items:
            print(f"\n  {title}:")
            for item in items:
                print(wrap(f"- {item}", "    "))
    if result.citations:
        print("\n  Citations:")
        for c in result.citations:
            page = f", page {c['page']}" if c.get("page") and c["section"] != f"Page {c['page']}" \
                else ""
            print(f"    [{c['chunk_id']}] {c['doc_id']} > {c['section']}{page}")
    if result.dropped_citations:
        print(f"  (dropped citations not backed by a tool result: {result.dropped_citations})")
    if result.escalation_reason:
        print(f"  Escalation: {result.escalation_reason}")
    if trace and result.tool_trace:
        print("\n  Trace:")
        for s in result.tool_trace:
            mark = "ok" if s["ok"] else "FAILED"
            args = f" {json.dumps(s['arguments'])}" if s.get("arguments") else ""
            print(f"    {s['step']:>2}. {s['type']:<9} {s['name']}{args}  ({s['latency_ms']} ms, "
                  f"{mark})")
            if s.get("result_summary"):
                limit = 300 if s["ok"] else 1500  # show failures in full
                print(wrap(s["result_summary"][:limit], "          -> "))


async def handle_pending(agent: HRAgent, session: Session, result: AgentResult,
                         trace: bool, ask) -> None:
    action = result.pending_action
    if not action:
        return
    print("\n  Proposed mock ticket (nothing is created until you confirm):")
    for key, value in action["preview"].items():
        print(wrap(f"{key}: {value}", "    "))
    answer = (await ask("  Create this ticket? [y/N] ")).strip().lower()
    show(await agent.confirm(session, action["token"], approve=answer in {"y", "yes"}), trace)


async def main_async(args: argparse.Namespace) -> int:
    tools = MCPToolClient()
    await tools.start()
    agent = HRAgent(LLMClient(), tools)
    session = Session(employee_id=args.employee.upper() if args.employee else None)
    trace = not args.no_trace

    async def ask(prompt: str) -> str:
        return await asyncio.to_thread(input, prompt)

    try:
        if args.message:
            result = await agent.run(" ".join(args.message), session)
            show(result, trace)
            await handle_pending(agent, session, result, trace, ask)
            return 0
        print(f"HR policy agent. Acting as: {session.employee_id or 'unknown'}. "
              ":as E-1002, :trace, :q")
        while True:
            try:
                line = (await ask("\nyou> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line in {":q", ":quit", ":exit"}:
                return 0
            if line.startswith(":as "):
                session = Session(employee_id=line[4:].strip().upper())
                print(f"Acting as {session.employee_id} (new session).")
                continue
            if line == ":trace":
                trace = not trace
                print(f"trace={'on' if trace else 'off'}")
                continue
            result = await agent.run(line, session)
            show(result, trace)
            await handle_pending(agent, session, result, trace, ask)
    finally:
        await tools.aclose()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows consoles can't print every character
    parser = argparse.ArgumentParser(description="Chat with the HR policy agent.")
    parser.add_argument("message", nargs="*", help="one question; omit for interactive mode")
    parser.add_argument("--employee", help="act as this employee id, e.g. E-1001")
    parser.add_argument("--no-trace", action="store_true", help="hide the tool trace")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
