import os

os.environ["USE_MOCK_LLM"] = "1"

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import get_session
from main import app
from mock_llm import MockLLM
from models import Base
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools.caculator_tool import CalculatorTool
from tools.current_time_tool import CurrentTimeTool
from tools.wikipedia_search_tool import WikipediaSearchTool


@pytest_asyncio.fixture
async def test_session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(test_session_factory):
    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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
