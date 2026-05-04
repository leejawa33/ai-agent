class MockLLM:
    def __init__(self, scenario: str = "default"):
        self.scenario = scenario

    def call(self, messages, tools=None) -> dict:
        last = messages[-1].get("content") or ""

        if self.scenario == "never_final":
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "mock_call_loop",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}
                }]
            }

        if "계산" in last:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "mock_call_1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "12*3+4"}'}
                }]
            }

        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "mock_call_final",
                "type": "function",
                "function": {"name": "final_answer", "arguments": '{"answer": "Mock LLM 응답입니다."}'}
            }]
        }

    def stream_call(self, messages, tools=None):
        result = self.call(messages, tools)
        if result.get("tool_calls"):
            args = result["tool_calls"][0]["function"]["arguments"]
            yield ("tool_token", args)
        yield ("done", result)

    async def acall(self, messages, tools=None) -> dict:
        return self.call(messages, tools)

    async def astream_call(self, messages, tools=None):
        result = self.call(messages, tools)
        if result.get("tool_calls"):
            args = result["tool_calls"][0]["function"]["arguments"]
            yield ("tool_token", args)
        yield ("done", result)
