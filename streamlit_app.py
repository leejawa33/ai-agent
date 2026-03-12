import streamlit as st
from react_agent import ReActAgent
# from llm import OpenAILLM
from mock_llm import MockLLM

from prompt import SYSTEM_PROMPT
from tools.caculator_tool import CalculatorTool
from tools.current_time_tool import CurrentTimeTool
from tools.wikipedia_search_tool import WikipediaSearchTool

st.set_page_config(page_title="ReAct Agent Demo", layout="wide")
st.title("🧠 ReAct Agent Demo")

agent = ReActAgent(
    llm=MockLLM(),
    tools={
        "calculator": CalculatorTool(),
        "current_time": CurrentTimeTool(),
        "wikipedia_search": WikipediaSearchTool(),  # ⭐ 추가
    },
    system_prompt=SYSTEM_PROMPT,
)

user_input = st.text_input("질문을 입력하세요")

if st.button("실행") and user_input:
    with st.spinner("실행 중..."):
        final_answer, steps = agent.run(user_input)

    st.success(final_answer)

    for step in steps:
        with st.expander(f"Step {step['step']}"):
            st.write("Thought:", step["thought"])
            st.write("Action:", step["action"])
            if step["tool"]:
                st.write("Tool:", step["tool"])
                st.write("Observation:", step["observation"])
