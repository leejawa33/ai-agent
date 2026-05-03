import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

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
