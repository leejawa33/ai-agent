import json
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from llm import OpenAILLM
from mock_llm import MockLLM
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools.caculator_tool import CalculatorTool
from tools.current_time_tool import CurrentTimeTool
from tools.wikipedia_search_tool import WikipediaSearchTool


def build_agent() -> ReActAgent:
    llm = MockLLM() if os.getenv("USE_MOCK_LLM") == "1" else OpenAILLM()
    tools = {
        "calculator": CalculatorTool(),
        "current_time": CurrentTimeTool(),
        "wikipedia_search": WikipediaSearchTool(),
    }
    return ReActAgent(llm=llm, tools=tools, system_prompt=SYSTEM_PROMPT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = build_agent()
    yield


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    max_steps: int = Field(default=5, ge=1, le=20)


class ChatResponse(BaseModel):
    answer: str
    steps: list[dict]


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    answer, steps = await app.state.agent.arun(req.message, max_steps=req.max_steps)
    return ChatResponse(answer=answer, steps=steps)


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, mode: Literal["step", "token"] = "step"):
    agent = app.state.agent

    async def step_generator():
        try:
            async for step_log in agent.arun_step_stream(req.message, max_steps=req.max_steps):
                yield _sse("step", step_log)
                if step_log["action"] == "final":
                    yield _sse("final", {"answer": step_log["final"]})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
        yield _sse("done", {})

    async def token_generator():
        try:
            async for event_type, data in agent.arun_token_stream(req.message, max_steps=req.max_steps):
                if event_type == "step_start":
                    yield _sse("step_start", {"step": data})
                elif event_type == "token":
                    yield _sse("token", {"text": data})
                elif event_type == "step_done":
                    yield _sse("step_done", data)
                elif event_type == "final":
                    yield _sse("final", {"answer": data})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
        yield _sse("done", {})

    gen = step_generator() if mode == "step" else token_generator()
    return EventSourceResponse(gen)
