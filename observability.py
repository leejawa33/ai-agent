import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    from langfuse import Langfuse  # type: ignore
except ImportError:
    Langfuse = None


def _build_langfuse_client():
    if Langfuse is None:
        return None
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )


_client = _build_langfuse_client()
TRACES_FILE = Path(os.getenv("TRACES_FILE", "traces.jsonl"))


# 단가는 1 토큰당 USD. 모델 추가 시 여기 한 줄.
MODEL_PRICING = {
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gpt-4o":      {"input": 2.50 / 1_000_000, "output": 10.0 / 1_000_000},
    "gpt-4.1-mini": {"input": 0.40 / 1_000_000, "output": 1.60 / 1_000_000},
    "mock":        {"input": 0.0, "output": 0.0},
}


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
    return input_tokens * p["input"] + output_tokens * p["output"]


class TraceRecorder:
    """한 채팅 요청에 대한 trace. LLM/Tool 이벤트를 누적해서 finalize 시 jsonl + Langfuse로 송신."""

    def __init__(self, conversation_id: int | None, query: str):
        self.trace_id = uuid.uuid4().hex
        self.conversation_id = conversation_id
        self.query = query
        self.events: list[dict] = []
        self.start_time = time.time()
        self.answer: str | None = None
        self.status: str = "ok"

        self._lf_trace = None
        if _client:
            self._lf_trace = _client.start_observation(
                name="chat",
                input={"query": query},
                metadata={"conversation_id": conversation_id},
            )

    def record_llm(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        cached_tokens: int = 0,
        request_summary: dict | None = None,
        response_summary: Any | None = None,
    ) -> None:
        cost = calc_cost(model, input_tokens, output_tokens)
        event = {
            "type": "llm",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": cost,
            "latency_ms": round(latency_ms, 2),
        }
        if request_summary:
            event["request"] = request_summary
        self.events.append(event)

        if self._lf_trace:
            gen = self._lf_trace.start_observation(
                as_type="generation",
                name=f"openai-{model}",
                model=model,
                input=request_summary,
                output=response_summary,
                usage_details={"input": input_tokens, "output": output_tokens},
                cost_details={"total": cost},
            )
            gen.end()

    def record_tool(self, name: str, args: dict, observation: str, latency_ms: float) -> None:
        event = {
            "type": "tool",
            "tool": name,
            "args": args,
            "observation": observation[:200],
            "latency_ms": round(latency_ms, 2),
        }
        self.events.append(event)

        if self._lf_trace:
            span = self._lf_trace.start_observation(
                name=f"tool-{name}",
                input=args,
                output=observation,
            )
            span.end()

    def finalize(self, answer: str | None, status: str = "ok") -> None:
        self.answer = answer
        self.status = status
        latency_ms = round((time.time() - self.start_time) * 1000, 2)

        llm_events = [e for e in self.events if e["type"] == "llm"]
        record = {
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "query": self.query,
            "answer": answer,
            "status": status,
            "latency_ms": latency_ms,
            "total_input_tokens": sum(e.get("input_tokens", 0) for e in llm_events),
            "total_output_tokens": sum(e.get("output_tokens", 0) for e in llm_events),
            "total_cached_tokens": sum(e.get("cached_tokens", 0) for e in llm_events),
            "total_cost_usd": round(sum(e.get("cost_usd", 0) for e in llm_events), 8),
            "llm_call_count": len(llm_events),
            "step_count": sum(1 for e in self.events if e["type"] == "tool") + 1,
            "events": self.events,
            "ts": time.time(),
        }
        with TRACES_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if self._lf_trace:
            self._lf_trace.update(output={"answer": answer, "status": status})
            self._lf_trace.end()
            if _client:
                _client.flush()


@contextmanager
def trace_chat(conversation_id: int | None, query: str) -> Iterator[TraceRecorder]:
    recorder = TraceRecorder(conversation_id, query)
    try:
        yield recorder
        if recorder.answer is None:
            recorder.finalize(answer=None, status="ok")
    except Exception as e:
        recorder.finalize(answer=None, status=f"error: {e}")
        raise


def read_traces_for_conversation(conversation_id: int) -> list[dict]:
    """로컬 jsonl에서 특정 대화의 trace를 읽어서 반환."""
    if not TRACES_FILE.exists():
        return []
    out = []
    with TRACES_FILE.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("conversation_id") == conversation_id:
                out.append(rec)
    return out
