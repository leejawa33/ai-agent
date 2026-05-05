# ReAct Agent — 학습용 데모 + 실서비스화 학습 트랙

ReAct(Reasoning + Acting) 패턴으로 구현한 AI Agent. 학습용 데모로 시작했고, **실서비스화 단계를 직접 적용해보면서 AI 엔지니어 면접 대비 자료까지 함께 정리**하는 프로젝트.

> 📌 **이 README의 역할**: 로드맵·진행도·기술 의사결정의 **단일 진실 소스(single source of truth)**. 모든 변경 사항은 여기에 갱신됨.

---

## 1. 빠른 실행

### Streamlit 데모 (UI)
**FastAPI 백엔드를 먼저 띄운 뒤 실행한다** (Streamlit은 더 이상 LLM/agent를 직접 호출하지 않고 `/chat/stream`을 SSE로 호출).
```bash
# 터미널 1: FastAPI 백엔드
.venv/bin/uvicorn main:app --port 8765

# 터미널 2: Streamlit
streamlit run streamlit_app.py
# 다른 호스트에 백엔드를 띄웠다면:
API_BASE_URL=http://otherhost:8765 streamlit run streamlit_app.py
```

### FastAPI 백엔드 (API)
```bash
.venv/bin/uvicorn main:app --port 8765
# mock LLM으로 비용 없이 동작 확인:
USE_MOCK_LLM=1 .venv/bin/uvicorn main:app --port 8765
```

`.env`에 `OPENAI_API_KEY` 설정 필요.

### 호출 예시
```bash
# 일반 JSON 응답 (응답에 conversation_id 포함)
curl -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"12 곱하기 3 더하기 4는?","max_steps":5}'

# 같은 대화에 이어서 (이전 conversation_id 사용)
curl -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"방금 결과를 두 배 해줘","conversation_id":1}'

# 대화 조회
curl http://127.0.0.1:8765/conversations/1

# Trace 조회 (로컬 JSONL — Langfuse 없어도 동작)
curl http://127.0.0.1:8765/traces/1

# SSE 스트리밍 - 스텝 모드 (기본, 첫 이벤트로 conversation_id 송신)
curl -N -X POST "http://127.0.0.1:8765/chat/stream?mode=step" \
  -H "Content-Type: application/json" \
  -d '{"message":"계산해줘"}'

# SSE 스트리밍 - 토큰 모드
curl -N -X POST "http://127.0.0.1:8765/chat/stream?mode=token" \
  -H "Content-Type: application/json" \
  -d '{"message":"계산해줘"}'
```

**SSE 이벤트 종류**:
- `step` 모드: `step` (각 스텝) → `final` → `done` / 실패 시 `error` → `done`
- `token` 모드: `step_start` → `token` (토큰 단위) → `step_done` → `final` → `done`

### 테스트 실행 (로컬 전용)
```bash
.venv/bin/pytest tests/ -v
```
- `pytest + pytest-asyncio + httpx` 사용
- MockLLM으로 OpenAI 비용 없이 회귀 검증
- CI 없음 (로컬 전용 정책)

---

## 2. 현재 구현된 것

### Agent 구조 (`react_agent.py`)
- ReAct 루프: `LLM(생각) → tool 선택 → 실행(병렬 가능) → 관찰 → 반복 → final_answer`
- OpenAI Function Calling 기반 (정규식 파싱 X)
- async 전용 (`arun`/`arun_step_stream`/`arun_token_stream`)
- `parallel_tool_calls=True` — 한 step에 여러 tool_call 동시 실행, `step_log["tools"]` 리스트
- 멀티턴 컨텍스트: `arun(history=...)` 로 과거 user/assistant 메시지 주입
- 모든 메서드에 `recorder` 인자 — observability 전파

### LLM 어댑터 (`llm.py`, `mock_llm.py`)
- `OpenAILLM`: `AsyncOpenAI` 기반, OpenAI usage(`prompt_tokens`/`completion_tokens`/`cached_tokens`) 자동 추출 → recorder 기록
- `MockLLM`: API 호출 없이 동작 검증용. `scenario` 파라미터로 분기 (`default`/`never_final`/`parallel_tools`)

### Tool (`tools/`)
- `@tool` 데코레이터 + Pydantic args 모델로 schema 자동 생성 (`tools/base.py`)
- `tools/*_tool.py` 자동 디스커버리 → `from tools import TOOLS`
- 등록된 도구: `calculator` / `current_time` / `wikipedia_search`
- `WIKI_MAX_CHARS` 환경변수로 wiki 결과 길이 캡 조정

### Persistence (`db.py`, `models.py`)
- SQLite + SQLAlchemy 2.0 async + `aiosqlite`
- 스키마: `conversations(id, title, created_at)` + `messages(id, conversation_id, role, content, created_at)`
- `app.lifespan`에서 `init_db()` (별도 마이그레이션 도구 X)

### Observability (`observability.py`)
- Langfuse SDK + 자체 JSONL 폴백 로거 (이중 트랙)
- `TraceRecorder`: LLM/Tool 이벤트 누적, finalize 시 `traces.jsonl` + Langfuse 동시 송신
- `MODEL_PRICING` 단가 테이블로 비용 자동 계산
- Langfuse 키 미설정 시 자동 no-op (폴백만 동작)

### API (`main.py`)
- `POST /chat` — JSON 응답 (answer + steps + conversation_id)
- `POST /chat/stream?mode=step|token` — SSE (sse-starlette, 명명 이벤트)
- `GET /conversations/{id}` — 대화 + 메시지 조회
- `GET /traces/{conversation_id}` — 로컬 JSONL trace 조회

### UI (`streamlit_app.py`)
- FastAPI 클라이언트 (httpx + httpx-sse), 직접 LLM 호출 X
- `API_BASE_URL` 환경변수 (기본 `http://127.0.0.1:8765`)
- 사이드바에 conversation_id + "새 대화 시작" 버튼

---

## 2.5 기술 스택 인벤토리

| 라이브러리 | 버전 | 용도 | 왜 이걸 골랐나 |
|---|---|---|---|
| `fastapi` | 0.128.0 | HTTP 백엔드 | async 네이티브, 자동 OpenAPI/Swagger UI, Pydantic 통합 |
| `uvicorn` | 0.40.0 | ASGI 서버 | FastAPI 표준 |
| `pydantic` | 2.12.5 | 입력 검증, tool args schema 자동 생성 | OpenAI Function Calling JSON Schema와 1:1 매핑, Pydantic-settings 연계 |
| `pydantic-settings` | 2.12.0 | 환경변수 → 설정 객체 | (현재 직접 활용 적지만 의존성 유지) |
| `openai` | 2.16.0 | LLM 호출 | 공식 SDK, async 지원, function calling 표준 |
| `python-dotenv` | (자동) | `.env` 로드 | 로컬 개발 표준 |
| `sse-starlette` | 3.4.1 | `EventSourceResponse` (SSE) | FastAPI 친화적, 비동기 generator → 명명 이벤트 자동 변환 |
| `httpx` + `httpx-sse` | 0.28.1 / 0.4.3 | Streamlit이 백엔드 호출 + SSE 파싱 | requests보다 modern, `connect_sse()` 한 줄로 SSE 처리 |
| `sqlalchemy[asyncio]` | 2.0.49 | ORM + async 세션 | 2.0 async 표준, 다른 DB로 갈아타기 쉬움 |
| `aiosqlite` | 0.22.1 | sqlite async 드라이버 | 별도 서버 불필요(파일 1개), 학습/면접 데모에 적합 |
| `langfuse` | 4.5.1 | LLM 관측성 SaaS SDK | 산업 표준 trace 트리 + 비용/토큰 가시화. 키 없으면 자동 no-op |
| `pytest` + `pytest-asyncio` | 9.0.3 / 1.3.0 | 테스트 러너 | Python 표준, async 함수 직접 테스트 |
| `pytest-recording` + `vcrpy` | 0.13.4 / 8.1.1 | Record & Replay (LLM 호출 cassette) | 실제 OpenAI 1회 녹화 → 이후 결정론적 회귀, 비용 0 |
| `streamlit` | 1.53.1 | 데모 UI | 빠른 데모, Phase 1.4부터 백엔드와 분리 |
| `requests` | 2.32.5 | wiki API 호출 (도구 내부) | 동기 호출 1개라 httpx 불필요 |

**의식적으로 도입 X**:
- LangChain 풀스택 — 추상화 무겁고 버전 호환 불안정 (ADR 2026-05-03 참조)
- LangGraph — Phase 7 멀티 에이전트에서만 비교 검토
- LlamaIndex — Phase 5 RAG에서 인덱서만 부분 도입 검토
- alembic — Phase X에 개념만, sqlite + create_all로 충분
- Postgres / Redis / Docker 배포 — Phase X 문서만, 로컬 전용 정책

---

## 2.6 Phase별 핵심 결정 요약 (한 줄씩)

| Phase | 무엇을 했나 | 핵심 결정 / WHY | 의식적으로 안 한 것 |
|---|---|---|---|
| **1.1** | async 전환 + `POST /chat` | sync→async 양쪽 병존(임시), Streamlit 호환 위해 sync 유지 | 풀 마이그레이션은 1.4에서 |
| **1.1.t** | pytest + TestClient 회귀 셋 | mock으로 코드 회귀만 잡음 (3층 테스트 전략의 1층) | 실제 LLM 통합은 Phase 4 |
| **1.2** | SSE `POST /chat/stream` | POST 채택 (긴 메시지·body 확장성 — OpenAI 표준 따름) | EventSource API 호환은 안 챙김 (어차피 Streamlit이 httpx 씀) |
| **1.3** | sqlite 영속화 + 멀티턴 | 단순 채팅 컨텍스트는 DB, 도구 trace는 별도(Langfuse) — 책임 분리 | users 테이블 X (단일 익명), tool_calls 테이블 X (Phase 6) |
| **1.4** | Streamlit→httpx + 동기 일괄 제거 | 백엔드/프론트 분리 위반 시 빨간불 뜨는 스모크 테스트 추가 | Streamlit AppTest UI 자동화 (ROI 낮음) |
| **1.5** | `@tool` 데코레이터 + Pydantic 자동 schema | tool 추가 시 등록 코드 0줄. 동시에 `next(iter(args))` 인자 매핑 버그 수정 | 서브셋 라우팅(도구 N개 적음), MCP(Phase 8) |
| **2** | Langfuse + 자체 JSONL 이중 트랙 | 외부 SaaS 의존 옵셔널 + 폴백 자체 로거. 수동 instrumenting(자동 `@observe()` X) — "왜 했는지" 설명력 | OpenTelemetry, Sentry, prompt 버저닝 |
| **3** | parallel_tool_calls + step_log 스키마 변경 + cached_tokens 측정 + cassette 인프라 | 측정 기반 최적화. **prompt caching은 임계 미달(850/1024)로 미발동 확인** → 트레이드오프 분석. cassette로 회귀 비용 0 | Wiki 2차 요약(구조 변경 큼), 히스토리 압축(Phase 6), 모델 라우팅(Phase 7), Semantic Cache |
| **4** | (다음) Eval 파이프라인 | 골든셋 + LLM-as-judge + opt-in 실행 (`pytest -m eval`) | — |
| **5** | (예정) RAG | chunking·hybrid·rerank 비교 측정 | — |
| **6** | (예정) Memory + Hallucination | 슬라이딩 윈도우, 압축 요약, citation 강제 | — |
| **7** | (예정) Multi-agent | Plan-and-Execute vs ReAct 비교, LangGraph 실험 | — |
| **8** | (예정) Guardrails + MCP | 도구 1개 MCP 서버로 분리 실험 | — |
| **X** | (문서만) Docker/JWT/CI/Cloud | 개념·예시 yaml만 (로컬 전용 정책) | 실배포 |

---

## 3. 실서비스화 학습 로드맵

### 목적과 원칙
- **목적**: 학습용 데모를 실서비스 수준으로 끌어올리는 과정에서 AI 엔지니어 면접 단골 주제(eval, 토큰 최적화, RAG, memory, observability 등)를 **직접 구현·측정·문서화**한다.
- **원칙**:
  1. 모든 걸 풀스택 구현하지 않는다. **AI 특화 주제는 깊게**, 일반 웹 백엔드 주제(인증, 배포, 시크릿 매니징)는 **개념만**.
  2. 각 Phase 끝에 **"왜 이렇게 했는가 / 트레이드오프" 문서**를 남긴다 → 면접 대비 자료가 된다.
  3. 측정 없는 최적화는 의미 없다. **숫자(토큰 절감률, 정답률, 지연 시간)** 를 함께 남긴다.
  4. **로컬 전용**. 클라우드 배포·CI/CD는 안 한다 (개념·문서만). 모든 실행/검증은 로컬 머신.

### Phase별 우선순위 (면접 ROI 기준 재배치)

| Phase | 주제 | 면접 빈도 | 상태 |
|---|---|---|---|
| **1** | FastAPI/async 백엔드 분리 + SSE 스트리밍 + 간단 영속화 | ★★ | 진행 중 |
| **2** | Observability (Langfuse) + 비용·토큰 측정 인프라 | ★★★ | 대기 |
| **3** | **토큰·비용 최적화 (측정 기반)** | ★★★ | 대기 |
| **4** | **Eval 파이프라인 (골든셋 + LLM-as-judge + 회귀)** | ★★★ | 대기 |
| **5** | **RAG 트랙 (chunking·하이브리드 검색·리랭킹·eval)** | ★★★ | 대기 |
| **6** | Memory + Hallucination 대응 (citation, grounding) | ★★ | 대기 |
| **7** | Multi-agent / Plan-and-Execute / LangGraph 비교 | ★★ | 대기 |
| **8** | Guardrails (프롬프트 인젝션, 도구 권한, HITL) | ★★ | 대기 |
| **X** | 일반 웹 주제 (Docker/JWT/Cloud Run) — **개념만** | ☆ | 문서화만 |

### Phase 1 — 백엔드 분리 (세부)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1.1 | OpenAILLM/MockLLM/ReActAgent에 async 메서드 추가, `main.py`에 `POST /chat` JSON 엔드포인트 | ✅ 완료 (2026-05-03) |
| 1.1.t | Phase 1.1 회귀 테스트 셋 (pytest + pytest-asyncio + TestClient + MockLLM, 11 tests) | ✅ 완료 (2026-05-03) |
| 1.2 | SSE 스트리밍 (`POST /chat/stream?mode=step\|token`, 명명 이벤트, error/done 처리) | ✅ 완료 (2026-05-05) |
| 1.3 | 영속화 (sqlite + sqlalchemy async, `conversations`/`messages` 스키마, conversation_id 컨텍스트 로딩, `GET /conversations/{id}`) | ✅ 완료 (2026-05-05) |
| 1.4 | Streamlit을 FastAPI 클라이언트로 전환 (httpx-sse), 동기 코드 일괄 제거 (`call`/`stream_call`/`run`/`run_step_stream`/`run_token_stream`) | ✅ 완료 (2026-05-05) |
| 1.5 | **Tool 등록 자동화** — `@tool` 데코레이터 + Pydantic args 모델로 schema 자동 생성, `tools/` 폴더 자동 디스커버리 (수동 dict 등록 제거), `_process_message` 인자 매핑 버그 동시 수정 | ✅ 완료 (2026-05-05) |

### Phase 2 — Observability + 측정 인프라 ✅ 완료 (2026-05-05)
- Langfuse SDK 통합 + **자체 JSONL 폴백 로거** (Langfuse 키 없으면 자동 no-op, 폴백만 동작)
- 모델 단가 테이블(`MODEL_PRICING`)로 비용 자동 계산 (`gpt-4o-mini`/`gpt-4o`/`gpt-4.1-mini`/`mock`)
- `TraceRecorder`로 LLM/Tool 이벤트 누적, `trace_chat()` context manager로 한 채팅 = 한 trace
- **수동 instrumenting**: `acall`/`astream_call`이 `recorder.record_llm()` 호출, `ToolWrapper.run`이 `recorder.record_tool()` 호출
- `GET /traces/{conversation_id}` — 로컬 JSONL에서 trace 조회 (Langfuse는 자체 UI 사용)
- 의존성: `langfuse 4.5.1`
- 환경변수: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (모두 옵셔널)
- 산출물: **"trace 한 건을 면접관에게 보여주며 설명할 수 있는 스크린샷 + 해석"** 문서 (Langfuse 가입 후 작성)

### Phase 3 — 토큰·비용 최적화 ✅ 완료 (2026-05-05)

**측정 결과 → `docs/token-optimization.md`**

직접 구현 + 측정 (★★★):
- [x] `parallel_tool_calls=True` 적용, `_process_message` 모든 tool_calls 순회 + `step_log["tools"]` 리스트 스키마 변경
- [x] `cached_tokens` 캡처(observability) + 시스템 프롬프트 강화 → **측정 결과: 프리픽스 850 토큰으로 1024 미달 → 캐시 미발동, 트레이드오프 분석 문서화**
- [x] 도구 결과 길이 캡 (`WIKI_MAX_CHARS` 환경변수)
- [x] **Record & Replay 도입** (`pytest-recording 0.13.4`, `vcrpy 8.1.1`) — Authorization 헤더 마스킹, `tests/cassettes/` 자동 관리

코드 한 번 구현 (★★):
- [ ] 메시지 히스토리 슬라이딩 윈도우 + LLM 요약 압축 → Phase 6 Memory에서 본격
- [ ] 모델 라우팅 (도구 선택은 mini, 최종 답변은 4o) → Phase 7 Multi-agent에서

개념 정리만 (★) — `docs/token-optimization.md` "의식적으로 안 한 것" 섹션:
- Semantic Cache (GPTCache) — 일관성/정확도 트레이드오프
- Plan-and-Execute로 LLM 호출 횟수 절감 (Phase 7과 중복)
- Batch API 50% 할인 — chat agent 부적합 이유 정리
- 도구 서브셋 라우팅 — 도구 N개 적을 땐 불필요

**1회 측정 비용**: ≈ $0.0015 (5쿼리 × 2 round)

### Phase 4 — Eval 파이프라인 (실제 LLM 품질 검증)
**Mock 테스트가 못 잡는 영역** — 프롬프트 품질, 도구 선택 정확도, 모델 업그레이드 영향, 할루시네이션, 종료 조건 — 을 실제 LLM 호출로 검증.

- 골든셋 30~50개 (`evals/golden_set.yaml`: 질문 + 기대 도구 사용 패턴 + 정답)
- 메트릭: 정답률, 평균 스텝 수, 평균 토큰, 도구 선택 정확도
- `pytest -m eval`로 명시적 실행 (평소 mock 테스트와 분리, opt-in 플래그)
- LLM-as-judge 한 종류는 직접 구현 (정답률 평가용 채점 LLM)
- 비용: gpt-4o-mini로 1회 전체 실행 1000원 미만 목표
- 산출물: **로컬 pytest 결과 리포트 + 메트릭 비교표 (모델/프롬프트 버전별)**

### Phase 5 — RAG 트랙
- 인덱싱: chunking 전략 2~3가지 비교 (고정 크기 / 의미 단위 / sliding window)
- 검색: 코사인 vs 하이브리드(BM25+벡터) 비교
- 리랭커 (cross-encoder) 적용 전후 비교
- Agent 도구로 RAG 통합 (`tools/rag_tool.py`)
- RAG eval (faithfulness, context relevance) — Ragas 또는 직접
- **Tool 수가 7~8개 넘으면 서브셋 라우팅 도입 검토** (1차 라우터 LLM이 카테고리 선택 → 본 LLM에 해당 카테고리만 전달)
- 산출물: **chunking 전략별 retrieval 정확도 비교표**

### Phase 6 — Memory + Hallucination 대응
- 단기 메모리 (대화 히스토리, sqlite)
- 컨텍스트 압축 (오래된 메시지 요약)
- 장기 메모리 (vectorDB에 사용자별 사실 저장/조회)
- Citation 강제 (답변에 출처 링크/문서 id)
- Grounding 검증 (답변이 검색 결과에서 도출됐는지 확인)

### Phase 7 — Multi-agent / Planning
- Plan-and-Execute 패턴 한 번 구현 → ReAct와 비교
- Critic/Reviewer 서브 에이전트 (LLM-as-judge로 답변 검증)
- LangGraph로 같은 그래프 재구현 → hand-rolled vs 프레임워크 비교 문서

### Phase 8 — Guardrails + MCP
- 프롬프트 인젝션 방어 (입력 필터)
- 도구 권한 정책 (read-only 자동 승인 / 부작용 도구는 HITL)
- 출력 정책 위반 검사 (Llama Guard 한 번 통합)
- **MCP (Model Context Protocol) 실험**: 기존 tool 1개를 MCP 서버로 분리, agent가 런타임에 디스커버리 — "MCP 써봤어요" 면접 답변 자료
- 산출물: **MCP 도입 전후 아키텍처 다이어그램 + 권한·격리 관점 비교 문서**

### Phase X — 일반 웹/인프라 주제 (구현 X, 문서만)
포트폴리오/면접에서 "이건 알지만 의식적으로 안 했다"고 말할 수 있게 정리. **로컬 전용 정책으로 실배포·CI/CD는 진행 안 함**.

- Dockerfile 1회 작성 (빌드만, 실배포 X)
- JWT 인증 흐름 다이어그램 + 코드 스켈레톤
- 시크릿 매니저 (Vault/Secrets Manager) 패턴
- Cloud Run/ECS 배포 흐름
- CI/CD (GitHub Actions, GitLab CI 등) — 개념·예시 yaml만 정리

---

## 4. 기술 의사결정 기록 (ADR-lite)

진행하면서 한 큰 결정과 이유를 짧게 남김.

### 2026-05-03 — LangChain 풀스택 도입하지 않기
- **결정**: LangChain 도입 X. 단일 목적 라이브러리(Langfuse, LlamaIndex의 인덱서, Llama Guard)는 부분 도입 OK. 멀티 에이전트/HITL이 필요해질 때만 LangGraph 검토.
- **이유**: 추상화 무겁고 버전 호환성 불안정. 현재 hand-rolled 코드의 강점은 "LLM 호출이 한눈에 보임"인데 이걸 잃지 않는 방향. 프레임워크에 갇히면 빠져나오기 어려움.

### 2026-05-03 — 면접 ROI 기준으로 로드맵 재배치
- **결정**: 인증/Docker/Cloud Run 같은 일반 웹 주제는 Phase X로 격하, AI 특화 주제(eval, 토큰 최적화, RAG)를 앞으로 당김.
- **이유**: 학습용 데모 → 실서비스화는 본질적으로 면접 대비 트랙. 일반 웹 주제는 면접에서 거의 안 물어봄. AI 특화 주제가 차별화 포인트.

### 2026-05-03 — DB는 sqlite로 시작
- **결정**: Phase 1.3에서 postgres/alembic 대신 sqlite + sqlalchemy async.
- **이유**: 면접용 데모 목적엔 충분. postgres 마이그레이션은 "필요 시 이렇게 한다"로 문서만.

### 2026-05-03 — 로컬 전용, CI/CD·실배포 제외
- **결정**: 모든 실행·검증을 로컬에서만 수행. GitHub Actions·Cloud Run·ECS·k8s 등 **클라우드/CI 인프라는 도입 X**. 관련 주제는 Phase X에 개념·예시 yaml만 정리.
- **이유**: 면접 대비 학습 프로젝트라는 본질에 맞춰 인프라 비용·복잡도 절감. AI 특화 주제 깊이에 시간 집중. CI 부재로 인한 회귀 리스크는 로컬 pytest로 완화.

### 2026-05-05 — Phase 3 step_log 스키마 변경 (parallel_tool_calls 지원)
- **결정**: `step_log["tool"]` / `step_log["observation"]` / `step_log["tool_call_id"]` (단일) → `step_log["tools"]: list[{name, args, tool_call_id, observation}]` (멀티)로 breaking change.
- **이유**: `parallel_tool_calls=True` 활성화 시 한 LLM 응답이 여러 tool_call을 반환할 수 있음. 단일 필드 유지 시 첫 항목 외 호출 결과 손실 + Streamlit/SSE 동시 수정 → 호환성 임시 유지보다 일괄 변경이 깔끔. `final_answer` 포함 시 다른 tool_call 무시(final 우선).

### 2026-05-05 — Observability: Langfuse + 폴백 JSONL 로거 (이중 트랙)
- **결정**: Langfuse SDK 통합 + 자체 `traces.jsonl` 로거를 동시에 운영. `LANGFUSE_PUBLIC_KEY` 미설정 시 Langfuse는 no-op, 로컬 JSONL은 항상 동작. instrumenting은 OpenAI/MockLLM/ToolWrapper에 명시적 `recorder` 인자 전파(자동 데코레이터 X).
- **이유**:
  1. 사용자가 Langfuse 가입 안 해도 즉시 메트릭 확보 → 학습 흐름 안 끊김
  2. 외부 SaaS 의존을 옵셔널로 만드는 추상화 능력 시연 (면접 답변 자료)
  3. 명시적 instrumenting이 "왜 했는지" 한 줄씩 설명하기 쉬움 (`@observe()`는 자동화돼서 답변 약함)
  4. JSONL은 Phase 4 eval에서 후처리·재현·분석에 그대로 활용 가능

### 2026-05-05 — LLM 테스트 3층 전략 (Mock / Replay / Real LLM)
- **결정**: 테스트를 3층으로 분리.
  1. **Mock 테스트** (현재 16개) — 코드/계약/구조 회귀. 매 변경마다 실행. 비용 0. → `pytest tests/`
  2. **Record & Replay** (Phase 3에 도입) — 실제 OpenAI 응답 1회 녹화 후 cassette로 재생. 결정론적, 비용 0. 프롬프트 변경 시만 재녹화.
  3. **Real LLM Eval** (Phase 4 본업) — 골든셋 30~50개로 모델/프롬프트 품질 검증. `pytest -m eval` opt-in. 1회 1000원 미만.
- **이유**: Mock 테스트만으로는 프롬프트 품질·도구 선택 정확도·모델 업그레이드 영향을 못 잡음. 매번 실제 LLM 호출은 비용·flakiness 부담. 산업 표준 피라미드(단위 70 / 통합 25 / E2E 5) 적용. 면접에서 가장 자주 묻는 LLM 테스트 전략.

### 2026-05-03 — async/FastAPI 백엔드 분리 (Phase 1.1)
- **결정**: 모든 LLM 호출/agent 루프를 async로 통일하고 FastAPI `POST /chat`을 진입점으로. 동기 코드는 1.4까지 Streamlit 호환 유지 후 일괄 제거.
- **이유**: ① 멀티 동시 요청 처리(I/O bound LLM/RAG/도구), ② Phase 2 Langfuse `@observe`/recorder가 async 친화적, ③ Phase 5 RAG 검색 동시성 활용. Streamlit은 sync 환경이라 1.4까지 두 경로 병존이 불가피.

### 2026-05-03 — 영속화 정책: 채팅 컨텍스트와 도구 trace를 분리 저장 (Phase 1.3)
- **결정**: DB(`messages`)에는 user/assistant 본문만 저장. 도구 호출/관찰/thought 같은 중간 step은 DB 저장 X — observability(Langfuse + traces.jsonl)로만 보냄.
- **이유**: ① 책임 분리(채팅 재현 ≠ 운영 관측), ② 메시지 테이블이 가벼워서 컨텍스트 재구성 빠름, ③ trace는 시간 지나면 폐기/요약하지만 채팅은 영구 보관 — 라이프사이클이 다름. Phase 6에서 audit 필요해지면 별도 테이블 추가.

### 2026-05-03 — Tool 아키텍처 단계적 진화
- **결정**:
  - Phase 1.5에 `@tool` 데코레이터 + Pydantic args 모델로 schema 자동 생성, `tools/` 자동 디스커버리 도입.
  - Phase 5에서 tool 수 늘면 서브셋 라우팅 검토.
  - Phase 8에서 MCP(Model Context Protocol) 서버로 tool 1개 분리 실험.
  - Code-as-Tool(SmolAgents 류)은 도입 X — 도메인 부적합. 개념만 정리.
- **이유**: 현재 수동 dict 등록은 tool 추가 시 N곳 수정·schema 수동 작성 등 마찰 큼. 데코레이터 자동화로 90% 마찰 제거. MCP는 면접 화제로 가치 매우 높고, 기존 tool 그대로 두고 1개만 분리해도 충분히 데모됨.

---

## 5. 참고: 원본 데모 기능

### 스트리밍 모드 (Streamlit)
| 모드 | 동작 방식 |
|------|-----------|
| 스텝 스트리밍 | 각 스텝(Thought → Tool → Observation)이 완료될 때마다 표시 |
| 토큰 스트리밍 | LLM이 토큰 생성하는 것을 실시간 표시 후 스텝 요약 |

### 알려진 이슈
- 복잡한 쿼리에서 LLM이 `final_answer` 호출 안 하고 max_steps 초과 가능 → Phase 6에서 프롬프트/루프 정책 개선 예정
- `tools/caculator_tool.py` 파일명 오타 (calculator)
- ~~`react_agent.py:96` `next(iter(args.values()))` — 인자 순서 의존, 도구별 명시적 매핑 필요~~ → **Phase 1.5에서 해결** (Pydantic 검증으로 dict 전달)
- ~~`agent.log` `.gitignore` 미반영~~ → 1.3 이후 `*.log` 처리됨
