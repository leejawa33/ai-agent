import os

os.environ["USE_MOCK_LLM"] = "1"

import pytest
from fastapi.testclient import TestClient

from main import app
from mock_llm import MockLLM
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools.caculator_tool import CalculatorTool
from tools.current_time_tool import CurrentTimeTool
from tools.wikipedia_search_tool import WikipediaSearchTool


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_agent(llm=None):
    return ReActAgent(
        llm=llm or MockLLM(),
        tools={
            "calculator": CalculatorTool(),
            "current_time": CurrentTimeTool(),
            "wikipedia_search": WikipediaSearchTool(),
        },
        system_prompt=SYSTEM_PROMPT,
    )
