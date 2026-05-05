import json
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from db import get_session, init_db
from llm import OpenAILLM
from mock_llm import MockLLM
from models import Conversation, Message
from observability import read_traces_for_conversation, trace_chat
from prompt import SYSTEM_PROMPT
from react_agent import ReActAgent
from tools import TOOLS


def build_agent() -> ReActAgent:
    llm = MockLLM() if os.getenv("USE_MOCK_LLM") == "1" else OpenAILLM()
    return ReActAgent(llm=llm, tools=TOOLS, system_prompt=SYSTEM_PROMPT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.agent = build_agent()
    yield


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    max_steps: int = Field(default=5, ge=1, le=20)
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    steps: list[dict]
    conversation_id: int


class MessageOut(BaseModel):
    id: int
    role: str
    content: str


class ConversationOut(BaseModel):
    id: int
    title: str | None
    messages: list[MessageOut]


async def _load_or_create_conversation(
    session: AsyncSession, conversation_id: int | None, first_user_message: str
) -> tuple[Conversation, list[dict]]:
    """conversation_id가 있으면 로드 + 히스토리 반환, 없으면 새로 생성."""
    if conversation_id is None:
        conv = Conversation(title=first_user_message[:30])
        session.add(conv)
        await session.flush()
        return conv, []

    conv = await session.get(Conversation, conversation_id, options=[selectinload(Conversation.messages)])
    if conv is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    history = [{"role": m.role, "content": m.content} for m in conv.messages]
    return conv, history


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_session)):
    conv, history = await _load_or_create_conversation(session, req.conversation_id, req.message)

    with trace_chat(conv.id, req.message) as recorder:
        answer, steps = await app.state.agent.arun(
            req.message, max_steps=req.max_steps, history=history, recorder=recorder,
        )
        recorder.finalize(answer=answer, status="ok")

    session.add_all([
        Message(conversation_id=conv.id, role="user", content=req.message),
        Message(conversation_id=conv.id, role="assistant", content=answer),
    ])
    await session.commit()

    return ChatResponse(answer=answer, steps=steps, conversation_id=conv.id)


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    mode: Literal["step", "token"] = "step",
    session: AsyncSession = Depends(get_session),
):
    conv, history = await _load_or_create_conversation(session, req.conversation_id, req.message)
    conv_id = conv.id
    agent = app.state.agent

    async def persist(answer: str):
        session.add_all([
            Message(conversation_id=conv_id, role="user", content=req.message),
            Message(conversation_id=conv_id, role="assistant", content=answer),
        ])
        await session.commit()

    async def step_generator():
        yield _sse("conversation_id", {"conversation_id": conv_id})
        final_answer: str | None = None
        with trace_chat(conv_id, req.message) as recorder:
            try:
                async for step_log in agent.arun_step_stream(
                    req.message, max_steps=req.max_steps, history=history, recorder=recorder,
                ):
                    yield _sse("step", step_log)
                    if step_log["action"] == "final":
                        final_answer = step_log["final"]
                        yield _sse("final", {"answer": final_answer})
                recorder.finalize(answer=final_answer, status="ok")
            except Exception as e:
                recorder.finalize(answer=None, status=f"error: {e}")
                yield _sse("error", {"message": str(e)})
        if final_answer is not None:
            await persist(final_answer)
        yield _sse("done", {})

    async def token_generator():
        yield _sse("conversation_id", {"conversation_id": conv_id})
        final_answer: str | None = None
        with trace_chat(conv_id, req.message) as recorder:
            try:
                async for event_type, data in agent.arun_token_stream(
                    req.message, max_steps=req.max_steps, history=history, recorder=recorder,
                ):
                    if event_type == "step_start":
                        yield _sse("step_start", {"step": data})
                    elif event_type == "token":
                        yield _sse("token", {"text": data})
                    elif event_type == "step_done":
                        yield _sse("step_done", data)
                    elif event_type == "final":
                        final_answer = data
                        yield _sse("final", {"answer": final_answer})
                recorder.finalize(answer=final_answer, status="ok")
            except Exception as e:
                recorder.finalize(answer=None, status=f"error: {e}")
                yield _sse("error", {"message": str(e)})
        if final_answer is not None:
            await persist(final_answer)
        yield _sse("done", {})

    gen = step_generator() if mode == "step" else token_generator()
    return EventSourceResponse(gen)


@app.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: int, session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, conversation_id, options=[selectinload(Conversation.messages)])
    if conv is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        messages=[MessageOut(id=m.id, role=m.role, content=m.content) for m in conv.messages],
    )


@app.get("/traces/{conversation_id}")
async def get_traces(conversation_id: int):
    traces = read_traces_for_conversation(conversation_id)
    return {"conversation_id": conversation_id, "count": len(traces), "traces": traces}
