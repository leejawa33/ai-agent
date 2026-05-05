class MockLLM:
    def __init__(self, scenario: str = "default"):
        self.scenario = scenario

    def _build_response(self, messages) -> dict:
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

        if self.scenario == "parallel_tools":
            # 첫 호출: calculator + current_time을 한 번에 → 두 번째 호출: final
            already_ran = any(m.get("role") == "tool" for m in messages)
            if not already_ran:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "mock_par_1", "type": "function",
                         "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}},
                        {"id": "mock_par_2", "type": "function",
                         "function": {"name": "current_time", "arguments": "{}"}},
                    ],
                }
            return {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "mock_call_final", "type": "function",
                    "function": {"name": "final_answer", "arguments": '{"answer": "Mock LLM 응답입니다."}'}
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

    async def acall(self, messages, tools=None, recorder=None) -> dict:
        result = self._build_response(messages)
        if recorder is not None:
            recorder.record_llm(
                model="mock",
                input_tokens=10 * len(messages),
                output_tokens=5,
                latency_ms=0.0,
                request_summary={"messages_count": len(messages)},
                response_summary=result,
            )
        return result

    async def astream_call(self, messages, tools=None, recorder=None):
        result = self._build_response(messages)
        if result.get("tool_calls"):
            args = result["tool_calls"][0]["function"]["arguments"]
            yield ("tool_token", args)
        if recorder is not None:
            recorder.record_llm(
                model="mock",
                input_tokens=10 * len(messages),
                output_tokens=5,
                latency_ms=0.0,
                request_summary={"messages_count": len(messages), "stream": True},
                response_summary=result,
            )
        yield ("done", result)
