"""Eval 파이프라인 자체의 스모크 테스트 (mock, 비용 0, 기본 실행에 포함).

골든셋 품질(정답률)은 여기서 검증하지 않는다 — 그건 pytest -m eval (실제 LLM)의 몫.
여기선 파이프라인이 깨지지 않았는지만: 골든셋 스키마, 러너 실행, 채점, 리포트 생성.
"""
import pytest

from evals.runner import (
    grade_case,
    load_golden_set,
    run_case,
    run_eval,
    summarize,
    write_report,
)
from mock_llm import MockLLM
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools import TOOLS


@pytest.fixture
def mock_agent():
    return ReActAgent(llm=MockLLM(), tools=TOOLS, system_prompt=SYSTEM_PROMPT)


def test_golden_set_loads_and_is_valid():
    cases = load_golden_set()
    assert 30 <= len(cases) <= 50, "골든셋은 30~50개 유지 (README Phase 4 스펙)"
    for c in cases:
        for name in c["expected_tools"]:
            assert name in TOOLS, f"{c['id']}: 존재하지 않는 도구 '{name}'"


async def test_run_case_captures_metrics(mock_agent, isolated_traces_file):
    # MockLLM default 시나리오: '계산' 포함 질문 → calculator → final
    case = {
        "id": "smoke-001",
        "category": "calc",
        "question": "계산해줘",
        "expected_tools": ["calculator"],
        "grading": {"method": "contains", "expected": "Mock"},
    }
    result = await run_case(mock_agent, case)
    assert result["status"] == "ok"
    assert result["tools_used"] == ["calculator"]
    assert result["step_count"] == 2
    assert result["llm_call_count"] == 2
    assert result["input_tokens"] > 0


async def test_contains_grading(mock_agent):
    ok = await grade_case(
        {"grading": {"method": "contains", "expected": "40"}},
        {"status": "ok", "answer": "결과는 40입니다"},
        judge=None,
    )
    assert ok["correct"] is True

    miss = await grade_case(
        {"grading": {"method": "contains", "expected": "40"}},
        {"status": "ok", "answer": "결과는 41입니다"},
        judge=None,
    )
    assert miss["correct"] is False

    err = await grade_case(
        {"grading": {"method": "contains", "expected": "40"}},
        {"status": "error: boom", "answer": None},
        judge=None,
    )
    assert err["correct"] is False and err["method"] == "error"


async def test_judge_case_skipped_without_judge(mock_agent):
    skipped = await grade_case(
        {"question": "q", "grading": {"method": "judge", "criteria": "..."}},
        {"status": "ok", "answer": "답"},
        judge=None,
    )
    assert skipped["correct"] is None and skipped["method"] == "skipped"


async def test_full_pipeline_with_mock_and_report(mock_agent, isolated_traces_file, tmp_path):
    cases = [
        {"id": "s1", "category": "calc", "question": "계산해줘",
         "expected_tools": ["calculator"], "grading": {"method": "contains", "expected": "Mock"}},
        {"id": "s2", "category": "no_tool", "question": "안녕",
         "expected_tools": [], "grading": {"method": "judge", "criteria": "인사"}},
    ]
    results = await run_eval(cases, mock_agent, judge=None, concurrency=2)
    agg = summarize(results, model="mock")

    assert agg["case_count"] == 2
    assert agg["graded_count"] == 1  # judge 케이스는 스킵
    assert agg["tool_accuracy"] == 1.0  # s1: calculator, s2: 도구 없음 → 둘 다 일치
    assert agg["agent_cost_usd"] == 0.0  # mock 단가 0

    report = write_report(results, agg, out_dir=tmp_path)
    text = report.read_text(encoding="utf-8")
    assert "정답률" in text and "s1" in text and "s2" in text
    assert (tmp_path / report.name.replace(".md", ".json")).exists()
