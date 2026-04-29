## ReAct Agent Demo 데모

ReAct Loop 구조 구현 목적

Workflow 기반 ReAct(Reasoning + Acting) AI 에이전트 시스템 구현

Streamlit 데모 UI 구성
- 명령어 : `streamlit run streamlit_app.py`
- `.env` 파일에 `OPENAI_API_KEY` 설정 필요

### 스트리밍 모드

UI 상단 라디오 버튼으로 두 가지 모드를 전환하며 비교할 수 있다.

| 모드 | 동작 방식 |
|------|-----------|
| **스텝 스트리밍** | 각 스텝(Thought → Tool → Observation)이 완료될 때마다 화면에 순차적으로 표시 |
| **토큰 스트리밍** | LLM이 글자를 생성하는 것을 실시간으로 표시한 뒤 스텝 요약으로 전환 |

### Tool 구현
- 계산기 (수학 연산)
- 현재 시간 조회
- 위키피디아 검색

