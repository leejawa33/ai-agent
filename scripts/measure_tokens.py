"""
Phase 3 토큰·비용 측정 스크립트.

여러 쿼리를 실제 OpenAI로 호출하면서 토큰/비용/지연/캐시 hit 비율을 수집해서 표로 출력한다.

사용:
  .venv/bin/python scripts/measure_tokens.py

필수: .env에 OPENAI_API_KEY. (USE_MOCK_LLM=1로는 실제 토큰을 못 잰다.)

옵션 토글 (환경변수):
  WIKI_MAX_CHARS=200       wiki 도구 결과 길이 캡 (기본 500)
"""
import asyncio
import os
import statistics
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 측정 전에 mock 비활성 보장
os.environ.pop("USE_MOCK_LLM", None)

from llm import OpenAILLM
from observability import trace_chat
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools import TOOLS


QUERIES = [
    "12 곱하기 3 더하기 4는 얼마야?",
    "(15+7)*4 계산해줘",
    "지금 몇 시야?",
    "Python (programming language) 위키 요약 알려줘",
    "100을 4로 나누면?",
]


async def run_one(agent: ReActAgent, query: str) -> dict:
    t0 = time.time()
    with trace_chat(conversation_id=None, query=query) as recorder:
        try:
            answer, steps = await agent.arun(query, max_steps=5, recorder=recorder)
            recorder.finalize(answer=answer, status="ok")
        except Exception as e:
            recorder.finalize(answer=None, status=f"error: {e}")
            return {"query": query, "error": str(e)}

    llm_events = [e for e in recorder.events if e["type"] == "llm"]
    return {
        "query": query,
        "latency_ms": round((time.time() - t0) * 1000, 1),
        "llm_calls": len(llm_events),
        "input_tokens": sum(e["input_tokens"] for e in llm_events),
        "output_tokens": sum(e["output_tokens"] for e in llm_events),
        "cached_tokens": sum(e.get("cached_tokens", 0) for e in llm_events),
        "cost_usd": round(sum(e["cost_usd"] for e in llm_events), 6),
        "tool_calls": sum(1 for e in recorder.events if e["type"] == "tool"),
        "answer_excerpt": (answer or "")[:60],
    }


async def main():
    agent = ReActAgent(llm=OpenAILLM(), tools=TOOLS, system_prompt=SYSTEM_PROMPT)
    print(f"환경: WIKI_MAX_CHARS={os.getenv('WIKI_MAX_CHARS', '500')}, parallel_tool_calls=True (코드 기본)")
    print("-" * 110)

    results = []
    # 같은 쿼리를 1회씩 두 번 돌려서 prompt caching 효과 확인 (두 번째에서 cached_tokens 증가 기대)
    for round_idx in (1, 2):
        print(f"\n=== Round {round_idx} (캐시 {'미스' if round_idx == 1 else '히트 기대'}) ===")
        for q in QUERIES:
            r = await run_one(agent, q)
            r["round"] = round_idx
            results.append(r)
            print(f"  [{r.get('latency_ms', '-'):>7}ms] llm={r.get('llm_calls','-')} "
                  f"in={r.get('input_tokens','-'):>5} out={r.get('output_tokens','-'):>4} "
                  f"cached={r.get('cached_tokens','-'):>5} ${r.get('cost_usd','-')} "
                  f"tools={r.get('tool_calls','-')} | {q[:50]}")

    # 라운드별 합계
    print("\n" + "=" * 110)
    for round_idx in (1, 2):
        rs = [r for r in results if r.get("round") == round_idx and "error" not in r]
        if not rs:
            continue
        total_in = sum(r["input_tokens"] for r in rs)
        total_out = sum(r["output_tokens"] for r in rs)
        total_cached = sum(r["cached_tokens"] for r in rs)
        total_cost = sum(r["cost_usd"] for r in rs)
        avg_latency = statistics.mean(r["latency_ms"] for r in rs)
        cache_hit_pct = (total_cached / total_in * 100) if total_in else 0
        print(f"Round {round_idx}: input={total_in} output={total_out} cached={total_cached} "
              f"({cache_hit_pct:.1f}%) cost=${total_cost:.6f} avg_latency={avg_latency:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())
