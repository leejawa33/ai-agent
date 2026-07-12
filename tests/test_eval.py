"""골든셋 eval — 실제 LLM 호출로 프롬프트 품질/도구 선택 정확도 검증 (테스트 3층 전략의 3층).

opt-in 실행 (기본 pytest에서 제외):
  .venv/bin/pytest -m eval -s
비용: gpt-4o-mini 기준 1회 전체 실행 ≈ $0.03~0.05 (README 목표 1000원 미만).
리포트는 evals/reports/에 저장됨 — 모델/프롬프트 버전 바꿔 재실행하면 비교표 재료가 된다.
"""
import os

import pytest

from evals.judge import Judge
from evals.runner import load_golden_set, run_eval, summarize, write_report

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY 필요"),
]

# 품질 게이트 — 미달 시 프롬프트/모델 회귀로 간주
MIN_ACCURACY = 0.80
MIN_TOOL_ACCURACY = 0.75


@pytest.fixture
def real_agent(monkeypatch):
    """USE_MOCK_LLM을 끄고 실제 OpenAI agent 빌드."""
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    from main import build_agent

    return build_agent()


async def test_golden_set_eval(real_agent, isolated_traces_file):
    from llm import OPENAI_MODEL

    cases = load_golden_set()
    judge = Judge()
    results = await run_eval(cases, real_agent, judge, concurrency=4)
    agg = summarize(results, model=OPENAI_MODEL, judge=judge)
    report_path = write_report(results, agg)

    print(
        f"\n정답률: {agg['accuracy']} | 도구 정확도: {agg['tool_accuracy']} "
        f"| 평균 스텝: {agg['avg_steps']} | 총 비용: ${agg['total_cost_usd']}"
    )
    print(f"리포트: {report_path}")

    failed = [r["id"] for r in results if r["grade_correct"] is False]
    assert agg["accuracy"] >= MIN_ACCURACY, f"정답률 {agg['accuracy']} < {MIN_ACCURACY}. 실패: {failed}"
    assert agg["tool_accuracy"] >= MIN_TOOL_ACCURACY, f"도구 정확도 {agg['tool_accuracy']} < {MIN_TOOL_ACCURACY}"
