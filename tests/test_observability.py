import json

import pytest

from observability import (
    MODEL_PRICING,
    TraceRecorder,
    calc_cost,
    read_traces_for_conversation,
    trace_chat,
)


def test_calc_cost_uses_model_pricing_table():
    p = MODEL_PRICING["gpt-4o-mini"]
    expected = 1000 * p["input"] + 500 * p["output"]
    assert calc_cost("gpt-4o-mini", 1000, 500) == pytest.approx(expected)


def test_calc_cost_returns_zero_for_unknown_model():
    assert calc_cost("unknown-model", 100, 50) == 0.0


def test_trace_chat_writes_jsonl_record(isolated_traces_file):
    with trace_chat(conversation_id=42, query="hi") as recorder:
        recorder.record_llm("gpt-4o-mini", input_tokens=100, output_tokens=50, latency_ms=120.0)
        recorder.record_tool("calculator", {"expression": "1+1"}, "2", latency_ms=0.5)
        recorder.finalize(answer="2", status="ok")

    lines = isolated_traces_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["conversation_id"] == 42
    assert rec["query"] == "hi"
    assert rec["answer"] == "2"
    assert rec["status"] == "ok"
    assert rec["total_input_tokens"] == 100
    assert rec["total_output_tokens"] == 50
    assert rec["total_cost_usd"] > 0
    assert len(rec["events"]) == 2
    assert rec["events"][0]["type"] == "llm"
    assert rec["events"][1]["type"] == "tool"


def test_chat_endpoint_emits_trace(client, isolated_traces_file):
    response = client.post("/chat", json={"message": "계산해줘"})
    conv_id = response.json()["conversation_id"]

    traces_response = client.get(f"/traces/{conv_id}")
    assert traces_response.status_code == 200
    body = traces_response.json()
    assert body["conversation_id"] == conv_id
    assert body["count"] >= 1
    trace = body["traces"][0]
    assert trace["query"] == "계산해줘"
    assert trace["answer"] == "Mock LLM 응답입니다."
    assert trace["total_input_tokens"] > 0
    assert any(e["type"] == "tool" and e["tool"] == "calculator" for e in trace["events"])


def test_get_traces_for_unknown_conversation_returns_empty(client):
    response = client.get("/traces/9999")
    assert response.status_code == 200
    assert response.json() == {"conversation_id": 9999, "count": 0, "traces": []}


def test_read_traces_for_conversation_handles_missing_file(isolated_traces_file):
    if isolated_traces_file.exists():
        isolated_traces_file.unlink()
    assert read_traces_for_conversation(123) == []
