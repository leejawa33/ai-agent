import pytest

from conftest import make_agent
from mock_llm import MockLLM


async def test_arun_calculator_query_uses_tool_then_finalizes():
    agent = make_agent()
    answer, steps = await agent.arun("계산해줘")
    assert len(steps) == 2
    assert steps[0]["action"] == "tool"
    assert steps[0]["tool"] == "calculator"
    assert steps[0]["observation"] == "40"
    assert steps[1]["action"] == "final"
    assert answer == "Mock LLM 응답입니다."


async def test_arun_simple_query_finalizes_immediately():
    agent = make_agent()
    answer, steps = await agent.arun("그냥 인사")
    assert len(steps) == 1
    assert steps[0]["action"] == "final"
    assert answer == "Mock LLM 응답입니다."


async def test_arun_raises_when_max_steps_exceeded():
    agent = make_agent(llm=MockLLM(scenario="never_final"))
    with pytest.raises(Exception, match="Max steps exceeded"):
        await agent.arun("계산해줘", max_steps=2)


async def test_arun_step_stream_yields_each_step():
    agent = make_agent()
    steps = []
    async for step_log in agent.arun_step_stream("계산해줘"):
        steps.append(step_log)
    assert len(steps) == 2
    assert steps[0]["action"] == "tool"
    assert steps[-1]["action"] == "final"


async def test_arun_token_stream_emits_expected_event_types():
    agent = make_agent()
    event_types = []
    final_payload = None
    async for event_type, data in agent.arun_token_stream("계산해줘"):
        event_types.append(event_type)
        if event_type == "final":
            final_payload = data
    assert "step_start" in event_types
    assert "token" in event_types
    assert "step_done" in event_types
    assert "final" in event_types
    assert final_payload == "Mock LLM 응답입니다."


def test_sync_run_still_works():
    """Streamlit이 1.4까지 동기 경로를 사용하므로 회귀 보호."""
    agent = make_agent()
    answer, steps = agent.run("계산해줘")
    assert len(steps) == 2
    assert steps[-1]["action"] == "final"
    assert answer == "Mock LLM 응답입니다."
