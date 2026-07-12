# Phase 1 복습 — 백엔드 분리

> Phase 1 (1.1 ~ 1.5)의 학습용 정리. 면접 대비 Q&A 포함.
> 원본 진실 소스: `README.md` Phase 1 세부 표 + ADR. 본 문서는 학습 편의 요약.

---

## 0. Phase 1이 왜 존재했나 (큰 그림)

학습용 데모로 만든 ReAct 에이전트가 **Streamlit 한 파일에 LLM 호출까지 다 묶여 있었음**. 실서비스라면 이 구조론 못 씀:
- 멀티 동시 사용자 처리 불가 (Streamlit은 단일 사용자 데모용)
- 인증·DB·관측성 붙일 자리 없음
- 프론트엔드 따로 만들기 불가능

→ **백엔드(FastAPI)와 프론트엔드(Streamlit)를 분리**하고, 그 과정에서 async/DB/스트리밍/Tool 자동화까지 다 정리한 게 Phase 1.

---

## 1.1 — async + `POST /chat`

### 한 일
- `OpenAILLM` / `MockLLM` / `ReActAgent`에 **비동기 메서드 추가** (`acall`, `astream_call`, `arun`, `arun_step_stream`, `arun_token_stream`)
- `main.py` Hello World 제거 → `POST /chat` JSON 엔드포인트
- `USE_MOCK_LLM=1` 환경변수로 비용 0 검증 가능
- 동기 메서드는 **임시 유지** (Streamlit이 1.4까지 씀)

### WHY async
1. LLM 호출이 I/O bound — sync면 thread가 5초 동안 자고 있어 자원 낭비. async면 같은 thread로 다른 사용자 요청 처리 가능
2. Phase 2 Langfuse·Phase 5 RAG가 async 친화 (한 요청 내 `asyncio.gather`로 병렬 검색 가능)
3. FastAPI가 async 네이티브

### 보충: Sync vs Async 자원 비교
- Sync (thread pool 100): 동시 100명 = thread 100개 (~수백MB), 5초 대기 동안 thread 점유
- Async (event loop 1): 동시 1000명 = thread 1개 + coroutine 1000개 (~수MB), `await` 시점에 양보

### Coroutine 핵심
- 단일 thread 안에서 N개 코루틴이 빠르게 교대 (동시이지만 병렬은 아님)
- `await` 지점에서 양보 → 이벤트 루프가 IO 끝난 다른 코루틴 깨움
- 진짜 병렬이 필요하면 멀티프로세스/워커 추가

### 핵심 코드 위치
- `llm.py:OpenAILLM.acall` — `AsyncOpenAI` 호출
- `react_agent.py:ReActAgent.arun` — async ReAct 루프
- `main.py:chat()` — `await agent.arun(...)`

### 면접 질문 예상
- Q: "왜 동기 코드도 같이 뒀어요?"
- A: "Streamlit이 1.4 전까지 sync 환경이라 호환을 위해 일시 병존시켰고, 1.4에서 일괄 제거했습니다. 처음부터 async만 갔으면 Streamlit이 깨졌을 거예요."

- Q: "왜 async 썼어요? Sync 서버도 thread pool로 동시 처리하잖아요?"
- A: "Sync도 처리하지만 LLM 호출이 5~30초 걸리는데 그동안 thread가 자원만 점유하고 노는 게 비효율입니다. async는 단일 thread로 수천 코루틴을 돌릴 수 있어 자원 효율이 5~10배 차이 납니다. RAG 같은 케이스에선 한 요청 내 병렬 IO도 가능해 응답 시간도 줄어듭니다."

---

## 1.1.t — pytest 회귀 테스트 셋

### 한 일
- `pytest` + `pytest-asyncio` + `httpx`(TestClient 내부) 도입
- `tests/conftest.py` — TestClient fixture, `make_agent` 헬퍼
- 11개 테스트:
  - `test_chat_endpoint.py` 5개 — `/chat` HTTP 흐름
  - `test_react_agent.py` 6개 — async/sync 에이전트 로직

### WHY 이 시점에 테스트
- 1.2 ~ 1.5 진행 중에 **회귀가 났는지 즉시 알기 위함**
- Mock LLM 사용 → 비용·flakiness 0
- "테스트 3층 전략" 1층(코드 회귀)에 해당

### 비유
- **pytest = JUnit**, **TestClient = MockMvc/RestAssured**

### 면접 질문 예상
- Q: "Mock 테스트가 의미 있나요? LLM이 진짜 답을 내는지 못 잡잖아요."
- A: "Mock은 코드 회귀(라우팅, 계약, async/sync 혼선)를 잡는 1층 테스트입니다. 모델/프롬프트 품질은 Phase 4 eval이 담당하는 별개 층이에요. 둘 다 필요합니다."

---

## 1.2 — SSE 스트리밍

### 한 일
- `POST /chat/stream?mode=step|token` 엔드포인트
- `sse-starlette`의 `EventSourceResponse` 사용
- **명명 이벤트 7종**: `step` / `step_start` / `token` / `step_done` / `final` / `done` / `error`
- 두 모드:
  - `step` — 스텝 완료 시마다 통째로 전송
  - `token` — LLM이 토큰 하나씩 생성하는 걸 실시간 전송

### WHY POST (GET 아님)
- README가 처음엔 GET이었지만 분석 후 POST로 변경
- 이유: 긴 메시지·body 확장성 (OpenAI/Anthropic 표준), 한글 URL 인코딩 부담 없음
- Streamlit이 EventSource API 안 쓰니 GET 장점 사라짐

### WHY 명명 이벤트 (vs `type` 필드)
- 클라이언트가 `addEventListener('step', ...)` 가능
- SSE 표준에 더 부합

### 핵심 코드 위치
- `main.py:chat_stream()` — `EventSourceResponse` + 두 generator
- `tests/test_chat_stream.py` — `parse_sse()` 헬퍼로 검증

### 면접 질문 예상
- Q: "왜 SSE를 썼고, WebSocket은 왜 안 썼나요?"
- A: "단방향 스트리밍에 SSE가 더 가볍고 HTTP 통과 잘 됩니다. WebSocket은 양방향 필요할 때, 예를 들어 사용자가 도중에 stop을 보내야 한다면 적합하지만 현재 흐름엔 오버킬입니다."

---

## 1.3 — sqlite 영속화 + 멀티턴

### 한 일
- **SQLite + SQLAlchemy 2.0 async + `aiosqlite`**
- 스키마 2개: `conversations(id, title, created_at)` + `messages(id, conversation_id, role, content, created_at)`
- `app.lifespan`에서 `init_db()` (마이그레이션 도구 X)
- `/chat`에 `conversation_id` 옵션 추가 — 있으면 히스토리 로드, 없으면 새 대화
- `GET /conversations/{id}` — 검증·디버깅용
- SSE 첫 이벤트로 `conversation_id` 송신

### WHY sqlite (postgres 아님)
- 학습/면접 데모엔 충분
- 별도 서버 불필요 (파일 1개)
- SQLAlchemy 추상화 덕에 postgres 마이그레이션 비용 낮음 (URL + alembic만)

### WHY 평문 메시지만 저장 (도구 trace 제외)
- 책임 분리: **채팅 재현 ≠ 운영 관측**
- 메시지 테이블이 가벼워야 컨텍스트 재구성 빠름
- 도구 trace는 라이프사이클 다름 (시간 지나면 폐기) → Langfuse/JSONL로
- audit 필요해지면 Phase 6에서 별도 테이블 추가 (마이그레이션)

### WHY users 테이블 X
- 단일 익명 사용자 (Phase X 인증과 함께 나중에)

### 핵심 코드 위치
- `models.py` — Conversation, Message
- `db.py` — engine, async session, `init_db`
- `main.py:_load_or_create_conversation()` — 히스토리 로드 로직
- `react_agent.py:_init_messages(history=...)` — 컨텍스트 주입

### 면접 질문 예상
- Q: "왜 도구 호출 trace는 DB에 안 저장했나요?"
- A: "채팅 재현용 메시지와 운영 관측용 trace는 라이프사이클이 다릅니다. trace는 시간 지나면 압축·폐기하지만 채팅은 영구 보관. 책임 분리해서 메시지 테이블을 가볍게 유지했고, 운영 metric은 observability(Langfuse + JSONL)로 갔습니다."

---

## 1.4 — Streamlit→httpx + 동기 코드 일괄 제거

### 한 일
- `streamlit_app.py` 갈아엎음 — LLM/agent/tools/prompt 직접 임포트 모두 제거
- `httpx-sse`로 `POST /chat/stream` 호출
- 사이드바: `conversation_id` 표시 + "새 대화 시작" 버튼 (`st.session_state` 멀티턴)
- `API_BASE_URL` 환경변수 (기본 `http://127.0.0.1:8765`)
- **동기 코드 전부 삭제** — `OpenAILLM.call/stream_call`, `MockLLM.call/stream_call`, `ReActAgent.run/run_step_stream/run_token_stream`
- 회귀 보호하던 sync 테스트도 제거 (역할 종료)
- **신규 스모크 테스트 2개** — Streamlit이 다시 LLM 직접 임포트하면 빨간불

### WHY 동기 코드 일괄 제거
- ADR `2026-05-03 — async/FastAPI 백엔드 분리` 정책 이행 (1.4까지만 유지)
- 두 경로 동기화 부담 사라짐
- 면접에서 "왜 sync 잔재 있나요?" 질문 차단

### WHY 스모크 테스트 추가
- "백엔드 분리" 원칙이 코드에 박혀 있어야 함
- 미래에 누가 실수로 Streamlit에 LLM import 추가하면 자동 빨간불

### 코드 라인 수 변화 (대폭 감소)
- llm.py: 162줄 → 102줄
- mock_llm.py: 50줄 → 48줄
- react_agent.py: 153줄 → 112줄

### 면접 질문 예상
- Q: "Streamlit으로 데모하는데 왜 굳이 분리했나요?"
- A: "Streamlit은 데모 UX용이고 LLM 호출 책임은 백엔드입니다. 분리해두면 React/Next.js로 프론트 갈아끼우거나, 모바일 클라이언트 추가가 자유롭습니다. 그리고 멀티 사용자 동시 처리, 인증, 레이트리밋 같은 것도 백엔드에 올라가야 하는데 Streamlit엔 못 붙입니다."

---

## 1.5 — `@tool` 데코레이터 + Pydantic 자동 schema

### 한 일
- `tools/base.py` 신규 — `@tool` 데코레이터, `ToolWrapper`, `REGISTRY`
- `tools/__init__.py` — `*_tool.py` 자동 import → `from tools import TOOLS`
- 3개 기존 tool 마이그레이션 (클래스 → 함수 + 데코레이터, 라인 수 절반)
- `ReActAgent._process_message`: `tool.run(str(first_value))` → `tool.run(args)` (Pydantic 검증 + kwargs)
- `main.py` / `tests/conftest.py`의 수동 dict 등록 제거 → `from tools import TOOLS` 한 줄

### Before / After

**Before** (수동 등록 + JSON Schema 손작성):
```python
class CalculatorTool:
    name = "calculator"
    schema = {"type": "function", "function": {"name": "calculator", ...}}
    def run(self, tool_input: str): ...
```

**After** (데코레이터 + Pydantic):
```python
class CalculatorArgs(BaseModel):
    expression: str = Field(..., description="...")

@tool(CalculatorArgs, description="수학 계산식을 실행합니다")
def calculator(expression: str) -> str: ...
```

### WHY 데코레이터 + Pydantic
1. **새 tool 추가 = 파일 하나만 만들면 끝** (등록 코드 0줄)
2. Schema가 타입과 100% 동기화 (JSON Schema 손작성 시 흔한 동기화 실패 차단)
3. **멀티 인자 도구 정상 동작** — 기존 `next(iter(args.values()))` 버그(첫 인자만 처리) 해결
4. 면접에서 "Pydantic으로 schema 자동 생성"이 좋은 답변 거리

### 핵심 코드 위치
- `tools/base.py:ToolWrapper.run()` — Pydantic validation → kwargs 호출
- `tools/__init__.py` — `pkgutil.iter_modules()`로 자동 디스커버리

### 의식적으로 안 한 것
- **서브셋 라우팅** — 도구 3개라 불필요 (Phase 5 RAG에서 7~8개 넘어가면 검토)
- **MCP 서버 분리** — Phase 8에서 1개만 실험 (면접 화제용)
- **Code-as-Tool** — 도메인 부적합

### 면접 질문 예상
- Q: "Tool 추가가 너무 번거로웠어요. 어떻게 풀었나요?"
- A: "데코레이터 + Pydantic args 모델로 OpenAI Function Calling JSON Schema 자동 생성하고, `tools/` 폴더 자동 디스커버리해서 등록 코드 자체를 없앴습니다. 동시에 기존 `next(iter(args))` 버그(멀티 인자 도구 첫 인자만 처리되던 것)도 Pydantic 검증으로 해결됐어요."

---

## Phase 1 종합 — 한 페이지 그림

```
[Before]                          [After]
streamlit_app.py                  ┌─ FastAPI (main.py)
  └─ ReActAgent (sync)            │    POST /chat
       └─ OpenAILLM (sync)        │    POST /chat/stream?mode=step|token
       └─ Tools (수동 dict)        │    GET /conversations/{id}
                                  │       │
                                  │       ▼
                                  │  ReActAgent.arun(history=...)
                                  │       │
                                  │       ▼
                                  │  OpenAILLM.acall (AsyncOpenAI)
                                  │       │
                                  │       ▼
                                  │  Tools (자동 디스커버리, Pydantic)
                                  │
                                  ├─ SQLite (conversations + messages)
                                  │
                                  └─ Streamlit (httpx 클라이언트)
                                       └─ /chat/stream SSE 구독
```

## 학습 포인트 5개 요약

1. **async가 LLM 앱의 디폴트** — I/O bound이라 (sync도 동시 처리 되지만 자원 효율 차이 큼)
2. **백엔드/프론트 분리는 작은 프로젝트도 가치 있음** — 미래 확장의 자유
3. **DB 책임 분리**: 채팅 재현용 vs 운영 관측용 데이터는 라이프사이클이 다름
4. **테스트는 3층** — Mock(코드) / Replay(결정론) / Real LLM eval(품질)
5. **자동화 가능한 등록은 자동화** — 데코레이터 + 폴더 디스커버리

---

## 다음 단계
- Phase 2 복습: [`phase-2-review.md`](phase-2-review.md) — Observability (Langfuse + 자체 JSONL 폴백)
- Phase 3 복습: [`phase-3-review.md`](phase-3-review.md) — 토큰 최적화 + Record & Replay (실측은 `token-optimization.md`)
- Phase 4 본격 실행: Eval 파이프라인
