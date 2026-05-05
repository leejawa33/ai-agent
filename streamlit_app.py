import json
import os

import httpx
import streamlit as st
from httpx_sse import connect_sse

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8765")

st.set_page_config(page_title="ReAct Agent Demo", layout="wide")
st.title("🧠 ReAct Agent Demo")

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None

with st.sidebar:
    st.header("대화")
    cid = st.session_state.conversation_id
    st.write(f"**conversation_id**: `{cid}`" if cid else "_새 대화_")
    if st.button("새 대화 시작", use_container_width=True):
        st.session_state.conversation_id = None
        st.rerun()
    st.divider()
    st.caption(f"API: `{API_BASE_URL}`")

mode = st.radio("스트리밍 모드", ["스텝 스트리밍", "토큰 스트리밍"], horizontal=True)
st.caption("스텝 스트리밍: 각 스텝 완료 시 표시 / 토큰 스트리밍: Function Call 인자가 생성되는 것을 실시간 표시")

user_input = st.text_input("질문을 입력하세요")


def stream_events(message: str, mode_param: str):
    body = {"message": message, "max_steps": 5}
    if st.session_state.conversation_id is not None:
        body["conversation_id"] = st.session_state.conversation_id

    with httpx.Client(timeout=60.0) as client:
        with connect_sse(
            client,
            "POST",
            f"{API_BASE_URL}/chat/stream",
            params={"mode": mode_param},
            json=body,
        ) as event_source:
            for sse in event_source.iter_sse():
                yield sse.event, json.loads(sse.data) if sse.data else {}


def render_step_log(s: dict, expanded: bool):
    if s["action"] == "final":
        label = f"Step {s['step']} — 최종 답변"
    else:
        tool_names = ", ".join(t["name"] for t in s.get("tools", []))
        label = f"Step {s['step']} — tools: {tool_names}"
    with st.expander(label, expanded=expanded):
        if s.get("thought"):
            st.write("**Thought:**", s["thought"])
        for t in s.get("tools", []):
            st.write(f"**Tool:** `{t['name']}`")
            st.write("**Args:**", t.get("args"))
            st.write("**Observation:**", t.get("observation"))
        if s.get("final"):
            st.success(s["final"])


if st.button("실행") and user_input:
    if mode == "스텝 스트리밍":
        result_area = st.empty()
        steps_done = []

        for event_name, data in stream_events(user_input, "step"):
            if event_name == "conversation_id":
                st.session_state.conversation_id = data["conversation_id"]
            elif event_name == "step":
                steps_done.append(data)
                with result_area.container():
                    for i, s in enumerate(steps_done):
                        render_step_log(s, expanded=(i == len(steps_done) - 1))
            elif event_name == "error":
                st.error(data.get("message", "unknown error"))

    else:
        stream_header = st.empty()
        stream_box = st.empty()
        steps_placeholder = st.empty()
        final_placeholder = st.empty()
        steps_done = []
        current_tokens = ""

        for event_name, data in stream_events(user_input, "token"):
            if event_name == "conversation_id":
                st.session_state.conversation_id = data["conversation_id"]
            elif event_name == "step_start":
                current_tokens = ""
                stream_header.markdown(f"**⏳ Step {data['step']} — Function Call 생성 중...**")
            elif event_name == "token":
                current_tokens += data["text"]
                stream_box.code(current_tokens, language="json")
            elif event_name == "step_done":
                stream_header.empty()
                stream_box.empty()
                steps_done.append(data)
                with steps_placeholder.container():
                    for s in steps_done:
                        render_step_log(s, expanded=False)
            elif event_name == "final":
                final_placeholder.success(data["answer"])
            elif event_name == "error":
                st.error(data.get("message", "unknown error"))
