import json

FINAL_ANSWER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "final_answer",
        "description": "충분한 정보가 모였을 때 최종 답변을 제출합니다",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "최종 답변"}
            },
            "required": ["answer"]
        }
    }
}

class ReActAgent:
    def __init__(self, llm, tools: dict, system_prompt: str):
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.tools_schema = [t.schema for t in tools.values()] + [FINAL_ANSWER_SCHEMA]

    async def arun(self, user_input: str, max_steps: int = 5, history: list | None = None):
        messages = self._init_messages(user_input, history)
        steps = []
        for step in range(1, max_steps + 1):
            message = await self.llm.acall(messages, self.tools_schema)
            step_log = self._process_message(step, message)
            steps.append(step_log)
            if step_log["action"] == "final":
                return step_log["final"], steps
            self._append_tool_result(messages, message, step_log["observation"], step_log["tool_call_id"])
        raise Exception("Max steps exceeded")

    async def arun_step_stream(self, user_input: str, max_steps: int = 5, history: list | None = None):
        messages = self._init_messages(user_input, history)
        for step in range(1, max_steps + 1):
            message = await self.llm.acall(messages, self.tools_schema)
            step_log = self._process_message(step, message)
            yield step_log
            if step_log["action"] == "final":
                return
            self._append_tool_result(messages, message, step_log["observation"], step_log["tool_call_id"])
        raise Exception("Max steps exceeded")

    async def arun_token_stream(self, user_input: str, max_steps: int = 5, history: list | None = None):
        messages = self._init_messages(user_input, history)
        for step in range(1, max_steps + 1):
            yield ("step_start", step)
            message = None
            async for event_type, data in self.llm.astream_call(messages, self.tools_schema):
                if event_type in ("token", "tool_token"):
                    yield ("token", data)
                elif event_type == "done":
                    message = data
            step_log = self._process_message(step, message)
            yield ("step_done", step_log)
            if step_log["action"] == "final":
                yield ("final", step_log["final"])
                return
            self._append_tool_result(messages, message, step_log["observation"], step_log["tool_call_id"])
        raise Exception("Max steps exceeded")

    def _init_messages(self, user_input: str, history: list | None = None):
        msgs = [{"role": "system", "content": self.system_prompt}]
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def _process_message(self, step: int, message: dict) -> dict:
        step_log = {
            "step": step,
            "thought": message.get("content") or "",
            "action": None,
            "tool": None,
            "tool_call_id": None,
            "observation": None,
            "final": None,
        }
        tool_calls = message.get("tool_calls")
        if tool_calls:
            tc = tool_calls[0]
            tool_name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}

            if tool_name == "final_answer":
                step_log["action"] = "final"
                step_log["final"] = args.get("answer", "")
                return step_log

            step_log["action"] = "tool"
            step_log["tool"] = tool_name
            step_log["tool_call_id"] = tc["id"]
            tool_input = next(iter(args.values()), "") if args else ""
            tool = self.tools.get(tool_name)
            step_log["observation"] = tool.run(str(tool_input)) if tool else "Tool not found"
        else:
            step_log["action"] = "final"
            step_log["final"] = message.get("content") or ""
        return step_log

    def _append_tool_result(self, messages, message: dict, observation: str, tool_call_id: str):
        messages.append(message)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(observation),
        })
