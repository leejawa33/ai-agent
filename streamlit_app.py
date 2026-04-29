import streamlit as st
from react_agent import ReActAgent
from llm import OpenAILLM
# from mock_llm import MockLLM

from prompt import SYSTEM_PROMPT
from tools.caculator_tool import CalculatorTool
from tools.current_time_tool import CurrentTimeTool
from tools.wikipedia_search_tool import WikipediaSearchTool

st.set_page_config(page_title="ReAct Agent Demo", layout="wide")
st.title("🧠 ReAct Agent Demo")

agent = ReActAgent(
    llm=OpenAILLM(),
    # llm=MockLLM(),
    tools={
        "calculator": CalculatorTool(),
        "current_time": CurrentTimeTool(),
        "wikipedia_search": WikipediaSearchTool(),
    },
    system_prompt=SYSTEM_PROMPT,
)

mode = st.radio("스트리밍 모드", ["스텝 스트리밍", "토큰 스트리밍"], horizontal=True)
st.caption("스텝 스트리밍: 각 스텝 완료 시 표시 / 토큰 스트리밍: Function Call 인자가 생성되는 것을 실시간 표시")

user_input = st.text_input("질문을 입력하세요")

if st.button("실행") and user_input:

    if mode == "스텝 스트리밍":
        result_area = st.empty()
        steps_done = []

        for step_log in agent.run_step_stream(user_input):
            steps_done.append(step_log)
            with result_area.container():
                for i, s in enumerate(steps_done):
                    is_latest = (i == len(steps_done) - 1)
                    label = f"Step {s['step']} — {'최종 답변' if s['action'] == 'final' else 'tool: ' + str(s['tool'])}"
                    with st.expander(label, expanded=is_latest):
                        if s["thought"]:
                            st.write("**Thought:**", s["thought"])
                        if s["tool"]:
                            st.write("**Tool:**", s["tool"])
                            st.write("**Observation:**", s["observation"])
                        if s["final"]:
                            st.success(s["final"])

    else:  # 토큰 스트리밍
        stream_header = st.empty()
        stream_box = st.empty()
        steps_placeholder = st.empty()
        final_placeholder = st.empty()
        steps_done = []
        current_tokens = ""

        for event_type, data in agent.run_token_stream(user_input):
            if event_type == "step_start":
                current_tokens = ""
                stream_header.markdown(f"**⏳ Step {data} — Function Call 생성 중...**")
            elif event_type == "token":
                current_tokens += data
                stream_box.code(current_tokens, language="json")
            elif event_type == "step_done":
                stream_header.empty()
                stream_box.empty()
                steps_done.append(data)
                with steps_placeholder.container():
                    for s in steps_done:
                        label = f"Step {s['step']} — {'최종 답변' if s['action'] == 'final' else 'tool: ' + str(s['tool'])}"
                        with st.expander(label, expanded=False):
                            if s["thought"]:
                                st.write("**Thought:**", s["thought"])
                            if s["tool"]:
                                st.write("**Tool:**", s["tool"])
                                st.write("**Observation:**", s["observation"])
                            if s["final"]:
                                st.write("**Output:**", s["final"])
            elif event_type == "final":
                final_placeholder.success(data)
