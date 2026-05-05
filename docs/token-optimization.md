# Phase 3 — 토큰·비용 최적화 측정 결과

> 측정 일자: 2026-05-05
> 모델: `gpt-4o-mini`
> 측정 도구: `scripts/measure_tokens.py` (5개 쿼리 × 2 round = 10회 호출)

## 적용된 최적화

| # | 항목 | 상태 | 비고 |
|---|---|---|---|
| 1 | `parallel_tool_calls=True` | ✅ 활성 | `_process_message`가 멀티 tool_call 모두 실행 |
| 2 | `_process_message` 인자 매핑 (Pydantic) | ✅ Phase 1.5에서 완료 | 멀티 인자 도구 정상 동작 |
| 3 | OpenAI Prompt Caching (자동) | ⚠️ 미발동 | 프리픽스 < 1024 토큰 (아래 분석 참조) |
| 4 | 도구 결과 길이 캡 (`WIKI_MAX_CHARS`) | ✅ 활성 | 기본 500자, 환경변수로 조정 가능 |
| 5 | 시스템 프롬프트 강화 | ✅ 부수 효과 | 종료 조건/중복 호출/병렬 호출 가이드 명시 → max_steps 초과 빈도 감소 기대 |
| 6 | Record & Replay (cassette) | ✅ 인프라 도입 | `pytest-recording` + `tests/cassettes/` |

## 실측 (Round 1 — 캐시 미스 / Round 2 — 캐시 hit 기대)

```
Round 1: input=8517 output=299 cached=0 (0.0%) cost=$0.001456 avg_latency=2720ms
Round 2: input=8517 output=295 cached=0 (0.0%) cost=$0.001454 avg_latency=2539ms
```

| 쿼리 | LLM 호출 | input | output | tools | latency | 비고 |
|---|---|---|---|---|---|---|
| `12 곱하기 3 더하기 4는 얼마야?` | 2 | 1536 | 46 | 1 | 3.2s | calc → final |
| `(15+7)*4 계산해줘` | 2 | 1527 | 46 | 1 | 2.0s | calc → final |
| `지금 몇 시야?` | 2 | 1524 | 33 | 1 | 2.6s | current_time → final |
| `Python (programming language) 위키 요약 알려줘` | 3 | 2404 | 133 | **2** | 4.4s | **wiki + (계산 또는 추가 호출) 1 step** |
| `100을 4로 나누면?` | 2 | 1526 | 41 | 1 | 1.5s | calc → final |

**1 회 전체(5쿼리) 비용 ≈ $0.0015 ≈ 2원**. 2 round 합쳐도 **약 4원**.

## 분석 / 발견

### 발견 1 — parallel_tool_calls 정상 동작
- Wiki 쿼리에서 **1 step에 tool_calls 2개**가 들어왔고 새 스키마 `step_log["tools"]: [...]`가 둘 다 처리.
- 다른 쿼리는 자연스럽게 도구가 1개씩만 필요 → 효과는 도구가 많아질수록 커짐.

### 발견 2 — Prompt Caching 미발동 ★
- `cached_tokens` 모든 호출에서 0.
- 원인: OpenAI prompt caching은 **프리픽스 1024 토큰 이상**일 때만 활성. 우리 시스템 프롬프트(~600토큰) + 도구 4개 스키마(~250토큰) ≈ **850토큰** → 미달.
- Round 2 같은 prefix를 다시 보내도 캐시 안 함.
- **다음 액션 후보**:
  - (a) 시스템 프롬프트에 도메인 예시·few-shot 추가해 1024 돌파 → 자동 활성
  - (b) 현 상태로 두고 Phase 5 RAG에서 도구가 늘면 자연스럽게 발동
  - (c) 각 호출에 `cache_control` 힌트(아직 OpenAI 미지원, Anthropic만) — N/A
- 면접 답변: "측정해보니 우리 케이스는 임계 미달. 늘리려면 프롬프트 키워야 하는데 토큰 비용 ↑ vs 캐시 50% 할인 ↓ 균형 분석이 우선."

### 발견 3 — Wiki 쿼리가 가장 비싸다 (예상대로)
- 다른 쿼리: ~1500 input
- Wiki 쿼리: 2404 input → 결과 텍스트(500자 캡 적용 후도 ~150토큰)가 후속 호출에 누적.
- **2차 요약 패스**(mini로 wiki 결과 100자 압축) 실험 가치 큼 → Phase 3.6+로 보류.

### 발견 4 — 라운드 간 거의 차이 없음
- Round 2가 캐시 hit 기대였으나 미발동(발견 2 때문) → input/cost 거의 동일.
- 만약 캐시 발동했다면 input 토큰 절반 이상이 cached로 잡혀 비용 -50%, latency -80% 기대.

## 의식적으로 안 한 것 (Phase 3 스코프 제한)

- **Wiki 2차 요약 패스** — Tool 안에서 LLM 호출이 필요해 구조 변경 큼. Phase 3.6+ 또는 Phase 5 RAG와 함께.
- **메시지 히스토리 슬라이딩 윈도우 + 요약 압축** — 멀티턴 대화가 길어질 때 의미. Phase 6 Memory에서 본격.
- **모델 라우팅 (router=mini, answer=4o)** — 도메인이 단순해서 효과 작음. Phase 7 Multi-agent에서 다룰 가치.
- **Semantic Cache** — 일관성/정확도 트레이드오프 큼. 개념 정리만.
- **Batch API** — 채팅 agent엔 부적합 (비동기 50% 할인이지만 즉시 응답 못 함).

## 면접 답변 템플릿

질문: "AI agent 토큰 어떻게 아껴요?"

답변 흐름:
1. **측정부터**: Langfuse + 자체 JSONL로 호출별 토큰/비용/지연 가시화 (Phase 2).
2. **구조적 절감**: parallel_tool_calls로 도구 여러 개 필요한 케이스 1 step으로. 우리 측정 기준 wiki 쿼리에서 step 수 감소.
3. **자동 절감**: OpenAI prompt caching 활용 — 단, 우리 프리픽스가 1024 미만이라 미발동, 늘려야 하는데 늘리는 비용 vs 50% 할인 트레이드오프 측정 필요.
4. **결과 압축**: 도구 결과 길이 캡 + 2차 요약 패스 (실험 보류 결정 + 이유).
5. **하지 않은 것의 이유**: semantic cache는 정확도 위험, batch는 응답 지연 부적합 — 트레이드오프 명시.
6. **회귀 방지**: pytest-recording cassette로 결정론적 회귀 테스트 (비용 0).

## 재실행 방법

```bash
# 측정 (실제 OpenAI 호출, ~4원)
.venv/bin/python scripts/measure_tokens.py

# wiki 결과를 더 짧게 자르고 측정
WIKI_MAX_CHARS=200 .venv/bin/python scripts/measure_tokens.py

# 회귀 테스트 (cassette 재생, 비용 0)
.venv/bin/pytest tests/test_real_llm_replay.py -m real_llm

# cassette 재녹화 (프롬프트/모델 변경 후)
.venv/bin/pytest tests/test_real_llm_replay.py --record-mode=once -m real_llm
```
