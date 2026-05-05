"""
실제 OpenAI를 호출해서 cassette로 녹화하고, 이후엔 cassette 재생으로 결정론적 회귀.

녹화/갱신 시: OPENAI_API_KEY를 .env에 설정 후
  pytest tests/test_real_llm_replay.py --record-mode=once -m real_llm
재생 시(기본): 키 없이 동작
  pytest tests/test_real_llm_replay.py -m real_llm

cassette는 tests/cassettes/<test_name>.yaml로 저장됨.
"""
import os

import pytest

import observability
from main import app, build_agent


pytestmark = pytest.mark.real_llm


@pytest.fixture
def real_llm_client(test_session_factory):
    """실제 OpenAI를 사용하도록 USE_MOCK_LLM을 끄고 agent를 다시 빌드."""
    from fastapi.testclient import TestClient
    from db import get_session

    original_mock = os.environ.pop("USE_MOCK_LLM", None)
    original_agent = getattr(app.state, "agent", None)
    app.state.agent = build_agent()

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        if original_mock is not None:
            os.environ["USE_MOCK_LLM"] = original_mock
        if original_agent is not None:
            app.state.agent = original_agent


@pytest.mark.vcr
def test_calculator_query_with_real_openai(real_llm_client, isolated_traces_file):
    response = real_llm_client.post("/chat", json={"message": "12 곱하기 3 더하기 4는?"})
    assert response.status_code == 200
    body = response.json()
    assert "40" in body["answer"]

    conv_id = body["conversation_id"]
    trace = real_llm_client.get(f"/traces/{conv_id}").json()["traces"][0]
    assert trace["total_input_tokens"] > 0
    assert trace["total_output_tokens"] > 0
    # gpt-4o-mini 비용은 매우 작지만 0보다 커야 함
    assert trace["total_cost_usd"] > 0
    assert trace["llm_call_count"] >= 1
