import json

import pytest

from conftest import make_agent
from mock_llm import MockLLM


def parse_sse(response) -> list[dict]:
    """text/event-stream을 [{event, data}] 리스트로 파싱."""
    events = []
    current = {"event": "message", "data": ""}
    for raw in response.iter_lines():
        line = raw if isinstance(raw, str) else raw.decode("utf-8")
        if line == "":
            if current["data"]:
                events.append(current)
            current = {"event": "message", "data": ""}
            continue
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
    if current["data"]:
        events.append(current)
    return events


def test_chat_stream_step_mode_emits_step_final_done(client):
    with client.stream("POST", "/chat/stream?mode=step", json={"message": "계산해줘"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response)

    names = [e["event"] for e in events]
    assert "step" in names
    assert "final" in names
    assert names[-1] == "done"

    final_event = next(e for e in events if e["event"] == "final")
    assert json.loads(final_event["data"])["answer"] == "Mock LLM 응답입니다."


def test_chat_stream_default_mode_is_step(client):
    with client.stream("POST", "/chat/stream", json={"message": "계산해줘"}) as response:
        assert response.status_code == 200
        events = parse_sse(response)

    names = [e["event"] for e in events]
    assert "step" in names


def test_chat_stream_token_mode_emits_token_events(client):
    with client.stream("POST", "/chat/stream?mode=token", json={"message": "계산해줘"}) as response:
        assert response.status_code == 200
        events = parse_sse(response)

    names = [e["event"] for e in events]
    assert "step_start" in names
    assert "token" in names
    assert "step_done" in names
    assert "final" in names
    assert names[-1] == "done"

    final_event = next(e for e in events if e["event"] == "final")
    assert json.loads(final_event["data"])["answer"] == "Mock LLM 응답입니다."


def test_chat_stream_invalid_mode_returns_422(client):
    response = client.post("/chat/stream?mode=invalid", json={"message": "hi"})
    assert response.status_code == 422


def test_chat_stream_emits_error_event_on_max_steps_exceeded(client):
    from main import app
    original = app.state.agent
    app.state.agent = make_agent(llm=MockLLM(scenario="never_final"))
    try:
        with client.stream(
            "POST",
            "/chat/stream?mode=step",
            json={"message": "계산해줘", "max_steps": 2},
        ) as response:
            assert response.status_code == 200
            events = parse_sse(response)
    finally:
        app.state.agent = original

    names = [e["event"] for e in events]
    assert "error" in names
    assert names[-1] == "done"
    error_event = next(e for e in events if e["event"] == "error")
    assert "Max steps" in json.loads(error_event["data"])["message"]
