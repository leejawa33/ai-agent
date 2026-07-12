# Phase 3 복습 — 토큰·비용 최적화 + Record & Replay

> Phase 3의 학습용 정리. 면접 대비 Q&A 포함.
> 원본 진실 소스: `README.md` Phase 3 섹션 + `docs/token-optimization.md`(실측 결과) + ADR `2026-05-05 — step_log 스키마 변경`, `2026-05-05 — LLM 테스트 3층 전략`. 본 문서는 학습 편의 요약.

---

## 0. Phase 3가 왜 존재했나 (큰 그림)

Phase 2에서 깔아둔 측정 인프라로 **실제 숫자를 보면서 최적화**하는 단계. 핵심은 "무엇을 했다"보다:

1. **측정 → 판단 → (적용 또는 보류)** 사이클을 돌렸다는 것
2. 최적화가 안 먹힌 케이스(prompt caching 미발동)를 **발견하고 원인 분석까지 문서화**한 것
3. 실제 LLM 응답을 cassette로 녹화해 **비용 0의 결정론적 회귀 테스트** 층을 추가한 것

면접에서 "토큰 어떻게 아꼈어요?"보다 "**아낄 수 있는지 어떻게 판단했어요?**"에 답할 수 있게 됨.

---

## 3.1 — parallel_tool_calls + step_log 스키마 변경

### 한 일
- `llm.py`: `parallel_tool_calls=True` (acall / astream_call 둘 다)
- `react_agent.py:_process_message`: 한 LLM 응답의 **모든 tool_calls 순회 실행**
- **step_log 스키마 breaking change**:
  - Before: `step_log["tool"]` / `step_log["observation"]` / `step_log["tool_call_id"]` (단일)
  - After: `step_log["tools"]: list[{name, args, tool_call_id, observation}]` (멀티)
- `_append_tool_result`: tool마다 `role: "tool"` 메시지를 각각 append (tool_call_id 매칭)
- `final_answer`가 tool_calls에 섞여 있으면 **final 우선, 나머지 무시**
- Streamlit / SSE 스키마 소비처 동시 수정

### WHY 스키마를 한 번에 갈았나 (호환 유지 안 하고)
- 단일 필드 유지하면 두 번째 이후 tool_call 결과가 **조용히 손실**됨 — 데이터 유실이 하위호환보다 나쁨
- 소비처(Streamlit, SSE, 테스트)가 전부 이 레포 안 → breaking change 비용이 낮을 때 일괄 변경이 깔끔
- 외부 API 소비자가 있었다면 버저닝 필요했을 것 (면접 꼬리질문 포인트)

### WHY final_answer 우선
- LLM이 `final_answer` + 다른 tool을 같이 부르는 엣지 케이스 존재
- final이 있다는 건 "답이 이미 정해졌다"는 뜻 → 나머지 실행은 토큰/시간 낭비 + 부작용 위험

### 실측 효과
- Wiki 쿼리에서 1 step에 tool_calls 2개 확인 → 스텝 수 감소 (LLM 왕복 1회 절약)
- 도구가 1개만 필요한 쿼리엔 자연히 효과 없음 — **도구가 늘수록 효과 커지는 구조적 최적화**

---

## 3.2 — Prompt Caching 측정 (★ 이 Phase의 백미)

### 한 일
- `llm.py`: `usage.prompt_tokens_details.cached_tokens` 추출 → recorder 기록
- `scripts/measure_tokens.py`: 5쿼리 × 2 round 측정 스크립트 (Round 2에서 캐시 hit 기대)
- 시스템 프롬프트 강화 (종료 조건/중복 호출/병렬 호출 가이드)

### 발견: 캐시 미발동
```
Round 1: input=8517 cached=0 (0.0%) cost=$0.001456
Round 2: input=8517 cached=0 (0.0%) cost=$0.001454   ← 캐시 hit 기대했으나 0
```
- 원인: OpenAI prompt caching은 **프리픽스 1024 토큰 이상**에서만 자동 활성
- 우리는 시스템 프롬프트(~600) + 도구 4개 스키마(~250) ≈ **850 토큰 → 임계 미달**

### 판단 (트레이드오프 분석)
| 선택지 | 내용 | 판단 |
|---|---|---|
| (a) 프롬프트 부풀려 1024 돌파 | few-shot 예시 추가 등 | 매 호출 +174토큰 이상 확정 지출 vs 캐시 50% 할인 — **역효과 가능, 보류** |
| (b) 현상 유지 | Phase 5 RAG에서 도구 늘면 자연 돌파 | ✅ 채택 |
| (c) `cache_control` 명시 힌트 | Anthropic만 지원, OpenAI 미지원 | N/A |

**교훈**: "캐시 켜면 50% 절감"을 그대로 믿지 말 것. 발동 조건(임계, 프리픽스 동일성)을 **실측으로 확인**해야 함.

---

## 3.3 — 도구 결과 길이 캡

- `WIKI_MAX_CHARS` 환경변수 (기본 500자) — wiki 결과가 후속 모든 LLM 호출에 누적되는 걸 차단
- 실측: wiki 쿼리 input 2404 토큰 vs 일반 쿼리 ~1500 토큰 — **도구 결과가 컨텍스트 누적 비용의 주범**
- 2차 요약 패스(LLM으로 wiki 결과 압축)는 구조 변경이 커서 보류 → Phase 5 RAG와 함께

---

## 3.4 — Record & Replay (테스트 3층 전략의 2층)

### 한 일
- `pytest-recording` (vcrpy 기반) 도입
- `tests/test_real_llm_replay.py` — `@pytest.mark.vcr` + `real_llm` 마커
- 실제 OpenAI 1회 호출 → `tests/cassettes/<test_name>.yaml`에 HTTP 요청/응답 녹화 → 이후 재생
- `conftest.py:vcr_config`:
  - `filter_headers`로 **Authorization / openai-organization / x-request-id 마스킹** (cassette가 git에 들어가므로 키 유출 차단)
  - `match_on`에 `body` 포함 — 프롬프트가 바뀌면 cassette 미스매치로 **재녹화 필요를 강제로 알림**

### 테스트 3층 전략 (ADR)
| 층 | 무엇 | 언제 실행 | 비용 |
|---|---|---|---|
| 1. Mock (`pytest tests/`) | 코드/계약/구조 회귀 | 매 변경 | 0 |
| 2. Replay (`pytest -m real_llm`) | 실제 API 응답 형태 기준 회귀, 결정론적 | 프롬프트/모델 변경 시 재녹화 | 녹화 1회만 |
| 3. Real Eval (`pytest -m eval`, Phase 4) | 프롬프트 품질·도구 선택 정확도 | opt-in | 1회 1000원 미만 |

### WHY Replay 층이 필요한가 (Mock이 있는데)
- Mock은 **우리가 상상한 응답**으로 테스트 — OpenAI 실제 응답 구조(예: tool_calls 직렬화, usage 필드)와 어긋나면 못 잡음
- Replay는 **실제 응답**을 재생 — SDK 업그레이드, 파싱 로직 변경 시 진짜 회귀를 잡음
- 그런데 결정론적이고 비용 0 → CI 없어도 부담 없이 반복 실행

### 재실행 커맨드
```bash
# 재생 (키 불필요, 비용 0)
.venv/bin/pytest tests/test_real_llm_replay.py -m real_llm
# 재녹화 (프롬프트/모델 변경 후)
.venv/bin/pytest tests/test_real_llm_replay.py --record-mode=once -m real_llm
# 토큰 측정 (실 호출, 약 2원)
.venv/bin/python scripts/measure_tokens.py
```

---

## 4. 의식적으로 안 한 것 (+ 이유 — 면접 답변 그대로 사용 가능)

| 안 한 것 | 이유 |
|---|---|
| Wiki 2차 요약 패스 | Tool 내부에서 LLM 호출 필요 → 구조 변경 큼. Phase 5 RAG와 함께 |
| 히스토리 슬라이딩 윈도우/요약 압축 | 멀티턴이 길어질 때 의미 → Phase 6 Memory 본업 |
| 모델 라우팅 (도구 선택 mini / 답변 4o) | 현재 도메인 단순해 효과 작음 → Phase 7 |
| Semantic Cache (GPTCache) | "비슷한 질문 = 같은 답" 가정이 정확도 리스크. 개념만 정리 |
| Batch API (50% 할인) | 비동기 처리라 즉시 응답 못 함 — 채팅 agent에 부적합 |
| 도구 서브셋 라우팅 | 도구 3~4개면 스키마 토큰 부담 작음. Phase 5에서 7~8개 넘으면 검토 |

---

## 5. 면접 질문 예상

- Q: "AI agent 토큰 비용 어떻게 아껴요?"
- A: (docs/token-optimization.md의 답변 템플릿) "① 먼저 측정 — 호출별 토큰/비용 가시화. ② 구조적 절감 — parallel_tool_calls로 왕복 감소. ③ 자동 절감 — prompt caching인데, 실측하니 프리픽스 850토큰으로 1024 임계 미달이라 미발동. 프롬프트를 키워서 돌파하는 건 확정 지출 vs 50% 할인 트레이드오프라 보류했습니다. ④ 도구 결과 길이 캡. ⑤ 안 한 것도 이유와 함께 — semantic cache는 정확도 리스크, batch는 지연 부적합."

- Q: "parallel_tool_calls 켜면 뭐가 달라지고, 뭘 고쳐야 했나요?"
- A: "한 LLM 응답에 tool_call이 여러 개 올 수 있게 됩니다. 기존 step_log가 단일 tool 전제라 두 번째 호출부터 결과가 유실돼서, tools 리스트로 스키마를 breaking change했습니다. 소비처가 전부 레포 안이라 일괄 변경했고, 외부 소비자가 있었다면 버저닝했을 겁니다. tool 결과 메시지도 tool_call_id별로 각각 append해야 OpenAI가 매칭합니다."

- Q: "LLM 테스트는 어떻게 해요? 응답이 비결정적이잖아요."
- A: "3층으로 나눕니다. Mock으로 코드 회귀(비용 0, 매번), cassette 재생으로 실제 응답 구조 기준 회귀(결정론적, 비용 0), 골든셋 eval로 품질 검증(opt-in, 실 호출). 층마다 잡는 버그 종류가 다릅니다 — Mock은 라우팅/계약, Replay는 파싱/SDK 호환, Eval은 프롬프트 품질/도구 선택 정확도."

- Q: "cassette를 git에 올리면 API 키 유출 아닌가요?"
- A: "vcr_config의 filter_headers로 Authorization 등 민감 헤더를 REDACTED로 마스킹하고 녹화합니다. 그리고 match_on에 body를 넣어서 프롬프트가 바뀌면 cassette 미스매치가 나게 — 낡은 cassette로 조용히 통과하는 걸 방지했습니다."

- Q: "prompt caching 왜 안 먹혔어요?"
- A: "OpenAI 자동 캐싱은 프리픽스 1024토큰 이상에서만 발동하는데 우리 프리픽스가 850토큰이었습니다. 실측 안 했으면 '캐시 적용했다'고 잘못 믿고 있었을 거예요. 측정이 최적화보다 먼저라는 걸 체감한 케이스입니다."

---

## 학습 포인트 5개 요약

1. **최적화는 측정 → 판단 → 적용/보류** — "적용했는데 안 먹힘"을 발견한 게 성과
2. **prompt caching은 발동 조건이 있다** — 1024토큰 임계, 프리픽스 동일성. 맹신 금지
3. **breaking change 판단 기준** — 소비자가 어디까지 있나 (전부 내부면 일괄, 외부면 버저닝)
4. **도구 결과가 컨텍스트 누적 비용의 주범** — 길이 캡은 가장 싼 최적화
5. **Record & Replay = 결정론과 리얼리즘의 절충** — Mock과 Eval 사이의 2층
