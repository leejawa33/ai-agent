# Phase 2 복습 — Observability + 측정 인프라

> Phase 2의 학습용 정리. 면접 대비 Q&A 포함.
> 원본 진실 소스: `README.md` Phase 2 섹션 + ADR `2026-05-05 — Observability: Langfuse + 폴백 JSONL 로거`. 본 문서는 학습 편의 요약.

---

## 0. Phase 2가 왜 존재했나 (큰 그림)

로드맵 원칙 3번: **"측정 없는 최적화는 의미 없다"**.

Phase 3(토큰 최적화)를 하려면 먼저 **호출별 토큰/비용/지연을 볼 수 있는 눈**이 필요했음. 그래서 최적화보다 관측을 먼저 깔았다:

- LLM 호출 1건마다: 모델, input/output/cached 토큰, 비용(USD), 지연(ms)
- Tool 실행 1건마다: 이름, args, observation, 지연(ms)
- 한 채팅 요청 = 한 trace로 묶어서 합계 확인

이게 없으면 Phase 3에서 "최적화했더니 좋아졌어요"를 **숫자 없이 주장**하게 됨 → 면접에서 바로 무너짐.

---

## 1. 아키텍처 — 이중 트랙 (Langfuse + 자체 JSONL)

```
한 채팅 요청
   │
   ▼
trace_chat(conv_id, query)  ← context manager, 한 채팅 = 한 trace
   │
   ▼
TraceRecorder ── record_llm(...)   ← OpenAILLM.acall / astream_call이 호출
   │          └─ record_tool(...)  ← ToolWrapper.run이 호출
   │
   ▼ finalize(answer, status)
   ├──→ traces.jsonl (로컬, 항상 동작)          ← 폴백 트랙
   └──→ Langfuse SDK (키 있을 때만, 없으면 no-op) ← SaaS 트랙
```

### 한 일
- `observability.py` 신규 — `TraceRecorder`, `trace_chat()`, `MODEL_PRICING`, `calc_cost()`
- `OpenAILLM.acall/astream_call`에 `recorder` 인자 추가 — OpenAI `usage`에서 `prompt_tokens`/`completion_tokens`/`cached_tokens` 추출해 기록
- `ToolWrapper.run`에 `recorder` 인자 추가 — tool 실행 시간·결과 기록
- `ReActAgent` 모든 메서드에 `recorder` 전파 (arun / arun_step_stream / arun_token_stream)
- `main.py`의 세 엔드포인트가 `with trace_chat(...)` 으로 감쌈 (에러 시 `status="error: ..."` 기록)
- `GET /traces/{conversation_id}` — 로컬 JSONL에서 trace 조회 API
- 스트리밍에서도 usage 확보: `stream_options={"include_usage": True}` (마지막 chunk에 usage 실림)

### WHY 이중 트랙 (Langfuse만 쓰지 않은 이유)
1. **Langfuse 가입 없이도 즉시 메트릭 확보** — 학습 흐름 안 끊김. `LANGFUSE_PUBLIC_KEY` 없으면 Langfuse는 자동 no-op, JSONL은 항상 동작
2. **외부 SaaS 의존을 옵셔널로 만드는 추상화** — 면접에서 "벤더 락인 어떻게 피했나" 답변 거리
3. **JSONL은 Phase 4 eval의 원료** — 후처리·재현·분석에 그대로 사용 가능
4. trace는 로컬 파일이라 디버깅할 때 `curl /traces/1`로 바로 확인

### WHY 수동 instrumenting (`@observe()` 자동 데코레이터 안 쓴 이유)
- Langfuse의 `@observe()`는 자동으로 다 잡아주지만, **"왜 이 지점을 계측했는지" 설명력이 없음**
- 명시적 `recorder` 인자 전파는 코드에서 데이터 흐름이 한눈에 보임 — hand-rolled의 강점 유지 (LangChain 안 쓴 이유와 같은 철학)
- recorder가 `None`이면 계측 스킵 → 테스트/스크립트에서 오버헤드 0

### WHY 비용을 직접 계산 (`MODEL_PRICING` 단가 테이블)
- OpenAI 응답에는 비용이 없음 (토큰 수만 옴) → 단가 테이블 × 토큰으로 직접 계산
- 모델 추가 시 한 줄 추가 (`gpt-4o-mini` / `gpt-4o` / `gpt-4.1-mini` / `mock`)
- `mock`은 단가 0 → mock 테스트 trace도 같은 파이프라인 통과 (분기 없음)

---

## 2. TraceRecorder 데이터 모델

**trace 1건 (traces.jsonl 한 줄)**:
```json
{
  "trace_id": "...", "conversation_id": 1, "query": "...", "answer": "...",
  "status": "ok",
  "latency_ms": 3200,
  "total_input_tokens": 1536, "total_output_tokens": 46, "total_cached_tokens": 0,
  "total_cost_usd": 0.00025, "llm_call_count": 2, "step_count": 2,
  "events": [ {"type": "llm", ...}, {"type": "tool", ...}, {"type": "llm", ...} ]
}
```

- `events`가 시간순 원본, `total_*`은 finalize 시 집계
- Langfuse 쪽은 같은 구조를 trace → generation(LLM) / span(Tool) 트리로 송신
- tool observation은 JSONL에 200자 캡 (`observation[:200]`) — 로그 비대 방지

### 핵심 코드 위치
- `observability.py:TraceRecorder.record_llm()` — 비용 계산 + Langfuse generation
- `observability.py:trace_chat()` — context manager, 예외 시에도 finalize 보장
- `llm.py:26-53 acall` — usage 추출 (`prompt_tokens_details.cached_tokens` 포함)
- `tools/base.py:ToolWrapper.run()` — tool 계측
- `main.py:83-87` — `/chat`에서 trace_chat 사용 패턴

---

## 3. 테스트

- `tests/test_observability.py` — recorder 기록/집계/파일 기록 검증
- `tests/conftest.py:isolated_traces_file` — **autouse fixture로 테스트마다 traces.jsonl 격리** (tmp_path + monkeypatch) → 테스트가 실제 trace 파일 오염 못 함

---

## 4. 의식적으로 안 한 것

| 안 한 것 | 이유 |
|---|---|
| OpenTelemetry | LLM 특화 관측(토큰/비용/프롬프트)은 Langfuse가 더 직접적. OTel은 일반 분산 트레이싱 표준이라 지금 오버킬 |
| Sentry (에러 트래킹) | 로컬 전용 프로젝트, status 필드로 충분 |
| Prompt 버저닝 (Langfuse Prompts) | Phase 4 eval에서 프롬프트 버전별 비교할 때 재검토 |
| `@observe()` 자동 계측 | 위 WHY 참조 — 설명력 때문에 수동 선택 |
| DB에 trace 저장 | ADR: 채팅 재현(DB)과 운영 관측(trace)은 라이프사이클이 다름 — Phase 1.3 결정 유지 |

---

## 5. 면접 질문 예상

- Q: "LLM 앱 observability 뭘 봤어요?"
- A: "호출 단위로 토큰(input/output/cached), 비용, 지연을 잡고 한 채팅 요청을 trace 하나로 묶었습니다. Langfuse로 trace 트리를 보고, 동시에 자체 JSONL 폴백을 둬서 SaaS 키 없이도 측정이 돌아가게 했어요. 이 JSONL이 Phase 4 eval의 분석 원료가 됩니다."

- Q: "Langfuse `@observe()` 데코레이터 쓰면 자동인데 왜 수동으로 했어요?"
- A: "자동 계측은 편하지만 어느 지점에서 무엇을 왜 재는지가 코드에 안 드러납니다. recorder 인자를 명시적으로 전파해서 계측 흐름이 한눈에 보이게 했고, recorder=None이면 오버헤드 0이라 테스트에도 부담 없습니다. 대신 새 LLM 어댑터 추가 시 계측 코드를 직접 넣어야 하는 트레이드오프는 있습니다."

- Q: "스트리밍 응답에서는 토큰 usage를 어떻게 잡아요?"
- A: "OpenAI는 기본적으로 스트리밍에 usage를 안 실어줍니다. `stream_options={\"include_usage\": True}`를 주면 마지막 chunk에 usage가 오는데, 그걸 받아서 스트림 종료 시점에 recorder에 기록했습니다."

- Q: "비용은 어떻게 계산해요? API가 알려주나요?"
- A: "안 알려줍니다. 모델별 단가 테이블을 두고 토큰 수 × 단가로 직접 계산합니다. 단가 변경/모델 추가가 테이블 한 줄이라 유지비가 낮아요."

---

## 학습 포인트 5개 요약

1. **최적화 전에 측정 인프라** — 숫자 없는 최적화 주장은 면접에서 무너짐
2. **외부 SaaS는 옵셔널하게** — 폴백 트랙 두면 의존성이 선택이 됨
3. **자동 계측 vs 수동 계측** — 편의성과 설명력의 트레이드오프, 학습용은 수동이 남는 게 많음
4. **채팅(DB)과 trace(관측)는 라이프사이클이 다르다** — 저장소 분리
5. **테스트 격리** — autouse fixture로 관측 파일도 오염 차단
