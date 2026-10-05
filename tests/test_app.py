from fastapi.testclient import TestClient

from app.evaluation import EVALUATION_CASES, run_evaluation
from app.main import app

client = TestClient(app)


def test_evaluation_dataset_has_required_size():
    assert len(EVALUATION_CASES) >= 20


def test_evaluation_runner_returns_summary():
    summary = run_evaluation()
    assert summary["total"] >= 20
    assert "by_category" in summary
    assert "groundedness" in summary


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mcp"]["connected"] is True


def test_chat_remote_work_question():
    response = client.post(
        "/chat",
        json={"message": "Can Ava work remotely from another state for six weeks?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert len(payload["citations"]) >= 1
    assert len(payload["tool_trace"]) >= 2
