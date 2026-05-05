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

    async def arun(self, user_input: str, max_steps: int = 5, history: list | None = None, recorder=None):
        messages = self._init_messages(user_input, history)
        steps = []
        for step in range(1, max_steps + 1):
            message = await self.llm.acall(messages, self.tools_schema, recorder=recorder)
            step_log = self._process_message(step, message, recorder=recorder)
            steps.append(step_log)
            if step_log["action"] == "final":
                return step_log["final"], steps
            self._append_tool_result(messages, message, step_log)
        raise Exception("Max steps exceeded")

    async def arun_step_stream(self, user_input: str, max_steps: int = 5, history: list | None = None, recorder=None):
        messages = self._init_messages(user_input, history)
        for step in range(1, max_steps + 1):
            message = await self.llm.acall(messages, self.tools_schema, recorder=recorder)
            step_log = self._process_message(step, message, recorder=recorder)
            yield step_log
            if step_log["action"] == "final":
                return
            self._append_tool_result(messages, message, step_log)
        raise Exception("Max steps exceeded")

    async def arun_token_stream(self, user_input: str, max_steps: int = 5, history: list | None = None, recorder=None):
        messages = self._init_messages(user_input, history)
        for step in range(1, max_steps + 1):
            yield ("step_start", step)
            message = None
            async for event_type, data in self.llm.astream_call(messages, self.tools_schema, recorder=recorder):
                if event_type in ("token", "tool_token"):
                    yield ("token", data)
                elif event_type == "done":
                    message = data
            step_log = self._process_message(step, message, recorder=recorder)
            yield ("step_done", step_log)
            if step_log["action"] == "final":
                yield ("final", step_log["final"])
                return
            self._append_tool_result(messages, message, step_log)
        raise Exception("Max steps exceeded")

    def _init_messages(self, user_input: str, history: list | None = None):
        msgs = [{"role": "system", "content": self.system_prompt}]
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def _process_message(self, step: int, message: dict, recorder=None) -> dict:
        step_log = {
            "step": step,
            "thought": message.get("content") or "",
            "action": None,
            "tools": [],
            "final": None,
        }
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            step_log["action"] = "final"
            step_log["final"] = message.get("content") or ""
            return step_log

        # final_answer가 포함되어 있으면 final로 처리 (다른 tool_call 무시)
        for tc in tool_calls:
            if tc["function"]["name"] == "final_answer":
                args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                step_log["action"] = "final"
                step_log["final"] = args.get("answer", "")
                return step_log

        # 일반 tool_call들을 모두 실행
        step_log["action"] = "tool"
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            tool = self.tools.get(tool_name)
            observation = tool.run(args, recorder=recorder) if tool else "Tool not found"
            step_log["tools"].append({
                "name": tool_name,
                "args": args,
                "tool_call_id": tc["id"],
                "observation": observation,
            })
        return step_log

    def _append_tool_result(self, messages, message: dict, step_log: dict):
        messages.append(message)
        for tool_entry in step_log["tools"]:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_entry["tool_call_id"],
                "content": str(tool_entry["observation"]),
            })
