import os

os.environ["USE_MOCK_LLM"] = "1"

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import observability
from db import get_session
from main import app
from mock_llm import MockLLM
from models import Base
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools import TOOLS


@pytest_asyncio.fixture
async def test_session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def isolated_traces_file(tmp_path, monkeypatch):
    """테스트마다 traces.jsonl을 격리해 파일 오염을 막는다."""
    traces_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(observability, "TRACES_FILE", traces_path)
    yield traces_path


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
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
