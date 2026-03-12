class MockLLM:
    def call(self, messages):
        last = messages[-1]["content"]

        if "계산" in last:
            return """
Thought: 계산이 필요하다
Action: tool
ToolName: calculator
Input: 12*3+4
"""
        return """
Thought: 충분한 정보가 모였다
Action: final
Output: Mock LLM 응답입니다.
"""
