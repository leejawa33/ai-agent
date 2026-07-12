"""Phase 4 Eval 러너 — 골든셋 실행 + 메트릭 집계 + 리포트 생성.

실행:
  # pytest로 (권장, 임계치 검증 포함)
  .venv/bin/pytest -m eval

  # 단독 스크립트로 (일부만 돌려보기 등)
  .venv/bin/python -m evals.runner --limit 5
  USE_MOCK_LLM=1 .venv/bin/python -m evals.runner --no-judge   # 파이프라인 확인용 (비용 0)

메트릭: 정답률 / 도구 선택 정확도 / 평균 스텝 수 / 평균 토큰 / 비용(agent+judge) / 지연.
리포트: evals/reports/eval_report_<ts>_<model>_<prompt_ver>.md + .json (버전별 비교용)
"""
import argparse
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from statistics import mean

import yaml

from observability import TraceRecorder, calc_cost
from prompt import PROMPT_VERSION

EVALS_DIR = Path(__file__).parent
GOLDEN_SET_PATH = EVALS_DIR / "golden_set.yaml"
REPORTS_DIR = EVALS_DIR / "reports"

VALID_METHODS = {"contains", "judge"}


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    cases = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    seen_ids = set()
    for c in cases:
        for key in ("id", "category", "question", "expected_tools", "grading"):
            assert key in c, f"골든셋 케이스에 '{key}' 누락: {c}"
        assert c["id"] not in seen_ids, f"골든셋 id 중복: {c['id']}"
        seen_ids.add(c["id"])
        method = c["grading"]["method"]
        assert method in VALID_METHODS, f"{c['id']}: 알 수 없는 채점 방법 '{method}'"
        if method == "contains":
            assert "expected" in c["grading"], f"{c['id']}: contains 채점엔 expected 필요"
        else:
            assert "criteria" in c["grading"], f"{c['id']}: judge 채점엔 criteria 필요"
    return cases


async def run_case(agent, case: dict, max_steps: int = 5) -> dict:
    """케이스 1건 실행. recorder로 토큰/비용 캡처 (trace는 conftest/CLI가 지정한 파일로)."""
    recorder = TraceRecorder(None, case["question"])
    t0 = time.time()
    try:
        answer, steps = await agent.arun(case["question"], max_steps=max_steps, recorder=recorder)
        status = "ok"
    except Exception as e:
        answer, steps, status = None, [], f"error: {e}"
    latency_ms = round((time.time() - t0) * 1000, 1)
    recorder.finalize(answer=answer, status=status)

    llm_events = [e for e in recorder.events if e["type"] == "llm"]
    tools_used = [t["name"] for s in steps for t in s.get("tools", [])]
    return {
        "answer": answer,
        "status": status,
        "step_count": len(steps),
        "tools_used": tools_used,
        "llm_call_count": len(llm_events),
        "input_tokens": sum(e["input_tokens"] for e in llm_events),
        "output_tokens": sum(e["output_tokens"] for e in llm_events),
        "cost_usd": sum(e["cost_usd"] for e in llm_events),
        "latency_ms": latency_ms,
    }


async def grade_case(case: dict, run_result: dict, judge) -> dict:
    """정답 여부 판정. contains는 문자열 매칭, judge는 채점 LLM. judge=None이면 judge 케이스 스킵."""
    if run_result["status"] != "ok":
        return {"correct": False, "reason": run_result["status"], "method": "error"}

    grading = case["grading"]
    answer = run_result["answer"] or ""
    if grading["method"] == "contains":
        ok = grading["expected"] in answer
        return {
            "correct": ok,
            "reason": f"기대값 '{grading['expected']}' {'포함' if ok else '미포함'}",
            "method": "contains",
        }

    if judge is None:
        return {"correct": None, "reason": "judge 미실행 (--no-judge)", "method": "skipped"}
    verdict = await judge.grade(case["question"], answer, grading["criteria"])
    return {**verdict, "method": "judge"}


async def run_eval(cases: list[dict], agent, judge, concurrency: int = 4, max_steps: int = 5) -> list[dict]:
    """전 케이스 실행 + 채점. 케이스별 결과 dict 리스트 반환."""
    sem = asyncio.Semaphore(concurrency)

    async def one(case):
        async with sem:
            run_result = await run_case(agent, case, max_steps=max_steps)
            grade = await grade_case(case, run_result, judge)
        tool_match = set(run_result["tools_used"]) == set(case["expected_tools"])
        return {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "expected_tools": case["expected_tools"],
            **run_result,
            **{f"grade_{k}": v for k, v in grade.items()},
            "tool_match": tool_match,
        }

    return list(await asyncio.gather(*(one(c) for c in cases)))


def summarize(results: list[dict], model: str, judge=None) -> dict:
    graded = [r for r in results if r["grade_correct"] is not None]
    correct = [r for r in graded if r["grade_correct"]]
    agg = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "case_count": len(results),
        "graded_count": len(graded),
        "accuracy": round(len(correct) / len(graded), 4) if graded else None,
        "tool_accuracy": round(sum(r["tool_match"] for r in results) / len(results), 4),
        "avg_steps": round(mean(r["step_count"] for r in results), 2),
        "avg_input_tokens": round(mean(r["input_tokens"] for r in results), 1),
        "avg_output_tokens": round(mean(r["output_tokens"] for r in results), 1),
        "avg_latency_ms": round(mean(r["latency_ms"] for r in results), 1),
        "agent_cost_usd": round(sum(r["cost_usd"] for r in results), 6),
        "judge_cost_usd": 0.0,
        "judge_call_count": 0,
    }
    if judge is not None:
        agg["judge_cost_usd"] = round(calc_cost(judge.model, judge.input_tokens, judge.output_tokens), 6)
        agg["judge_call_count"] = judge.call_count
    agg["total_cost_usd"] = round(agg["agent_cost_usd"] + agg["judge_cost_usd"], 6)

    per_category = {}
    for cat in sorted({r["category"] for r in results}):
        rs = [r for r in results if r["category"] == cat]
        gs = [r for r in rs if r["grade_correct"] is not None]
        per_category[cat] = {
            "count": len(rs),
            "accuracy": round(sum(r["grade_correct"] for r in gs) / len(gs), 4) if gs else None,
            "tool_accuracy": round(sum(r["tool_match"] for r in rs) / len(rs), 4),
            "avg_steps": round(mean(r["step_count"] for r in rs), 2),
        }
    agg["per_category"] = per_category
    return agg


def _fmt(v):
    return "-" if v is None else v


def write_report(results: list[dict], agg: dict, out_dir: Path = REPORTS_DIR) -> Path:
    """리포트를 md + json으로 저장. 파일명에 모델/프롬프트 버전 포함 → 버전별 비교 가능."""
    import json as _json

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"eval_report_{ts}_{agg['model']}_{agg['prompt_version']}"

    (out_dir / f"{stem}.json").write_text(
        _json.dumps({"aggregates": agg, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Eval Report — {agg['model']} / prompt {agg['prompt_version']}",
        "",
        f"> 실행: {ts} | 케이스 {agg['case_count']}개 (채점 {agg['graded_count']}개)",
        "",
        "## 종합",
        "",
        "| 메트릭 | 값 |",
        "|---|---|",
        f"| 정답률 | {_fmt(agg['accuracy'])} |",
        f"| 도구 선택 정확도 | {agg['tool_accuracy']} |",
        f"| 평균 스텝 수 | {agg['avg_steps']} |",
        f"| 평균 input 토큰 | {agg['avg_input_tokens']} |",
        f"| 평균 output 토큰 | {agg['avg_output_tokens']} |",
        f"| 평균 지연(ms) | {agg['avg_latency_ms']} |",
        f"| agent 비용 | ${agg['agent_cost_usd']} |",
        f"| judge 비용 ({agg['judge_call_count']}회) | ${agg['judge_cost_usd']} |",
        f"| 총 비용 | ${agg['total_cost_usd']} |",
        "",
        "## 카테고리별",
        "",
        "| 카테고리 | 케이스 | 정답률 | 도구 정확도 | 평균 스텝 |",
        "|---|---|---|---|---|",
    ]
    for cat, m in agg["per_category"].items():
        lines.append(f"| {cat} | {m['count']} | {_fmt(m['accuracy'])} | {m['tool_accuracy']} | {m['avg_steps']} |")

    lines += ["", "## 케이스별", "", "| id | 정답 | 도구 일치 | 스텝 | 토큰(in/out) | 사용 도구 |", "|---|---|---|---|---|---|"]
    for r in results:
        mark = {True: "✅", False: "❌", None: "⏭"}[r["grade_correct"]]
        tmark = "✅" if r["tool_match"] else f"❌ (기대: {r['expected_tools'] or '없음'})"
        lines.append(
            f"| {r['id']} | {mark} | {tmark} | {r['step_count']} "
            f"| {r['input_tokens']}/{r['output_tokens']} | {', '.join(r['tools_used']) or '-'} |"
        )

    failures = [r for r in results if r["grade_correct"] is False or not r["tool_match"]]
    if failures:
        lines += ["", "## 실패 상세", ""]
        for r in failures:
            lines += [
                f"### {r['id']} — {r['question']}",
                f"- 답변: {r['answer']}",
                f"- 판정: {r['grade_reason']} ({r['grade_method']})",
                f"- 도구: 기대 {r['expected_tools']} / 실제 {r['tools_used']}",
                "",
            ]

    path = out_dir / f"{stem}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="골든셋 eval 실행")
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N개만 실행")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--no-judge", action="store_true", help="judge 케이스 스킵 (mock 파이프라인 확인용)")
    args = parser.parse_args()

    use_mock = os.getenv("USE_MOCK_LLM") == "1"
    if not use_mock and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY 필요 (또는 USE_MOCK_LLM=1)")

    # 단독 실행 시 eval trace는 리포트 폴더로 격리 (운영 traces.jsonl 오염 방지)
    import observability
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    observability.TRACES_FILE = REPORTS_DIR / "eval_traces.jsonl"

    from main import build_agent
    from evals.judge import Judge

    cases = load_golden_set()
    if args.limit:
        cases = cases[: args.limit]
    agent = build_agent()
    judge = None if (args.no_judge or use_mock) else Judge()
    if use_mock:
        model = "mock"
    else:
        from llm import OPENAI_MODEL
        model = OPENAI_MODEL

    results = asyncio.run(run_eval(cases, agent, judge, concurrency=args.concurrency, max_steps=args.max_steps))
    agg = summarize(results, model=model, judge=judge)
    report_path = write_report(results, agg)

    print(f"\n정답률: {_fmt(agg['accuracy'])} | 도구 정확도: {agg['tool_accuracy']} | 총 비용: ${agg['total_cost_usd']}")
    print(f"리포트: {report_path}")


if __name__ == "__main__":
    main()
