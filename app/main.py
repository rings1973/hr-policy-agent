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
          body {
            font-family: Arial, sans-serif;
            margin: 0;
            background: linear-gradient(180deg, #f3f8ff 0%, #eef1f7 100%);
            color: #1f2937;
          }
          .card {
            max-width: 860px;
            margin: 2.5rem auto;
            background: #ffffff;
            padding: 2rem;
            border-radius: 18px;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
          }
          h1 {
            margin: 0 0 1rem 0;
            font-size: 2rem;
            color: #1f4fd8;
          }
          .subtitle {
            color: #52607a;
            margin-bottom: 1rem;
          }
          textarea {
            width: 100%;
            min-height: 110px;
            box-sizing: border-box;
            padding: 1rem;
            border: 1px solid #d8e0ef;
            border-radius: 12px;
            font-size: 1rem;
            resize: vertical;
            background: #f8fbff;
          }
          button {
            margin-top: 1rem;
            padding: 0.8rem 1.5rem;
            background: linear-gradient(135deg, #2d6df6, #2257d6);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
          }
          button:hover { filter: brightness(0.98); }
          #output {
            margin-top: 1.5rem;
          }
          .chat {
            display: flex;
            flex-direction: column;
            gap: 1rem;
          }
          .assistant-message,
          .source-card,
          .trace-card {
            padding: 1rem 1.1rem;
            border-radius: 14px;
            background: #f8fafc;
            border: 1px solid #e5e7eb;
          }
          .assistant-message {
            background: #edf7ff;
            border-color: #dbeafe;
            line-height: 1.6;
          }
          .label {
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-weight: 700;
            color: #495d7d;
            margin-bottom: 0.45rem;
          }
          .status-pill {
            display: inline-block;
            margin-top: 0.8rem;
            padding: 0.35rem 0.7rem;
            background: #dcfce7;
            color: #166534;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
          }
          .source-card ul, .trace-card ul {
            margin: 0.4rem 0 0 1.1rem;
            padding: 0;
          }
          .source-card li, .trace-card li {
            margin-bottom: 0.5rem;
            line-height: 1.5;
          }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>HR Policy Assistant</h1>
          <div class="subtitle">Ask a question about PTO, remote work, benefits, or company policy.</div>
          <textarea id="message" placeholder="Example: Can Ava work remotely from another state for six weeks?"></textarea>
          <button id="ask-button">Ask</button>
          <div id="output"></div>
        </div>
        <script>
          function safeText(value) {
            return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          }

          window.renderResult = function(data) {
            const output = document.getElementById('output');
            const citations = Array.isArray(data.citations) ? data.citations : [];
            const trace = Array.isArray(data.tool_trace) ? data.tool_trace : [];
            const statusText = data.status ? data.status.toUpperCase() : 'OK';
            const answerText = String(data.answer || 'I can help with HR policy questions.').split(String.fromCharCode(10)).join('<br>');

            const sourceHtml = citations.length ? '<ul>' + citations.map(function(item) {
              const title = safeText(item.title || item.document_id || 'Policy');
              const section = safeText(item.section || 'Policy section');
              const snippet = safeText(item.snippet || '');
              return '<li><strong>' + title + '</strong> — ' + section + '<br>' + snippet + '</li>';
            }).join('') + '</ul>' : '<p>No policy references were returned.</p>';

            const traceHtml = trace.length ? '<ul>' + trace.map(function(item) {
              const toolName = safeText(item.tool || 'Tool');
              const argsText = safeText(JSON.stringify(item.arguments || {}));
              return '<li><strong>' + toolName + '</strong>: ' + argsText + '</li>';
            }).join('') + '</ul>' : '<p>No extra checks were needed.</p>';

            output.innerHTML =
              '<div class="chat">' +
              '<div class="assistant-message">' +
              '<div class="label">Assistant</div>' +
              '<div>' + answerText + '</div>' +
              '<div class="status-pill">' + statusText + '</div>' +
              '</div>' +
              '<div class="source-card">' +
              '<div class="label">Sources</div>' +
              sourceHtml +
              '</div>' +
              '<div class="trace-card">' +
              '<div class="label">What I checked</div>' +
              traceHtml +
              '</div>' +
              '</div>';
          };

          window.ask = async function() {
            const message = document.getElementById('message').value.trim();
            const output = document.getElementById('output');
            if (!message) {
              output.innerHTML =
                '<div class="assistant-message">' +
                '<div class="label">Assistant</div>' +
                '<div>Please ask a question about PTO, remote work, benefits, or company policy.</div>' +
                '</div>';
              return;
            }

            output.innerHTML =
              '<div class="assistant-message">' +
              '<div class="label">Assistant</div>' +
              '<div>Thinking about your HR question...</div>' +
              '</div>';

            const res = await fetch('/chat', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({message})
            });
            const data = await res.json();
            window.renderResult(data);
          };

          document.addEventListener('DOMContentLoaded', function () {
            const button = document.getElementById('ask-button');
            if (button) {
              button.addEventListener('click', window.ask);
            }
          });
        </script>
      </body>
    </html>
    """
