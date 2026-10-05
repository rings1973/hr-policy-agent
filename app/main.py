from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.agent import HRPolicyAgent
from app.evaluation import run_evaluation
from app.mcp_server import MCPToolServer
from app.rag import EmployeeStore, PolicyRAG

app = FastAPI(title="HR Policy Agent")
rag = PolicyRAG()
employee_store = EmployeeStore()
mcp_server = MCPToolServer(rag=rag, employee_store=employee_store)
agent = HRPolicyAgent(mcp_server=mcp_server)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "app": "hr-policy-agent",
        "mcp": {"connected": True, "tool_count": len(mcp_server.list_tools())},
    }


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, object]:
    result = agent.handle_message(request.message)
    return {
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "tool_trace": result.get("tool_trace", []),
        "status": result.get("status", "ok"),
    }


@app.get("/evaluate")
def evaluate() -> dict[str, object]:
    return run_evaluation()


@app.get("/demo-tasks")
def demo_tasks() -> dict[str, list[str]]:
    return {
        "tasks": [
            "Can Ava work remotely from another state for six weeks?",
            "What is Ava's current PTO balance and what steps are required to request time off?",
        ]
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
    <html>
      <head>
        <title>HR Policy Agent</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 2rem; background: #f4f7fb; }
          .card { max-width: 800px; margin: 0 auto; background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
          textarea { width: 100%; height: 100px; padding: 0.75rem; }
          button { padding: 0.75rem 1.25rem; margin-top: 0.75rem; background: #1f6feb; color: white; border: none; border-radius: 8px; cursor: pointer; }
          #output { margin-top: 1.5rem; white-space: pre-wrap; }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>HR Policy Agent</h1>
          <textarea id="message" placeholder="Ask about PTO, remote work, benefits, or policy compliance..."></textarea>
          <button onclick="ask()">Ask</button>
          <div id="output"></div>
        </div>
        <script>
          async function ask() {
            const message = document.getElementById('message').value;
            const output = document.getElementById('output');
            output.textContent = 'Thinking...';
            const res = await fetch('/chat', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({message})
            });
            const data = await res.json();
            output.textContent = JSON.stringify(data, null, 2);
          }
        </script>
      </body>
    </html>
    """
