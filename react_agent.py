import re

class ReActAgent:
    def __init__(self, llm, tools: dict, system_prompt: str):
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

    def run(self, user_input: str, max_steps: int = 5):
        messages = self._init_messages(user_input)
        steps = []
        for step in range(1, max_steps + 1):
            response = self.llm.call(messages)
            step_log = self._process_response(step, response)
            steps.append(step_log)
            if step_log["action"] == "final":
                return step_log["final"], steps
            self._append_observation(messages, response, step_log["observation"])
        raise Exception("Max steps exceeded")

    def run_step_stream(self, user_input: str, max_steps: int = 5):
        """각 스텝이 완료될 때마다 step_log를 yield"""
        messages = self._init_messages(user_input)
        for step in range(1, max_steps + 1):
            response = self.llm.call(messages)
            step_log = self._process_response(step, response)
            yield step_log
            if step_log["action"] == "final":
                return
            self._append_observation(messages, response, step_log["observation"])
        raise Exception("Max steps exceeded")

    def run_token_stream(self, user_input: str, max_steps: int = 5):
        """토큰 단위 스트리밍. 이벤트 튜플을 yield:
        ("step_start", step_num)
        ("token", token_str)
        ("step_done", step_log)
        ("final", answer_str)
        """
        messages = self._init_messages(user_input)
        for step in range(1, max_steps + 1):
            yield ("step_start", step)
            full_response = ""
            for token, full_text in self.llm.stream_call(messages):
                yield ("token", token)
                full_response = full_text
            step_log = self._process_response(step, full_response)
            yield ("step_done", step_log)
            if step_log["action"] == "final":
                yield ("final", step_log["final"])
                return
            self._append_observation(messages, full_response, step_log["observation"])
        raise Exception("Max steps exceeded")

    def _init_messages(self, user_input: str):
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

    def _process_response(self, step: int, response: str) -> dict:
        thought = self._parse("Thought", response)
        action = self._parse("Action", response)
        step_log = {
            "step": step,
            "thought": thought,
            "action": action,
            "tool": None,
            "observation": None,
            "final": None,
        }
        if action == "final":
            step_log["final"] = self._parse("Output", response)
            return step_log
        tool_name = self._parse("ToolName", response)
        tool_input = self._parse("Input", response)
        tool = self.tools.get(tool_name)
        step_log["tool"] = tool_name
        step_log["observation"] = tool.run(tool_input) if tool else "Tool not found"
        return step_log

    def _append_observation(self, messages, response, observation):
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": f"Observation: {observation}"})

    def _parse(self, key: str, text: str) -> str:
        match = re.search(rf"{key}:\s*(.*)", text)
        if not match:
            raise Exception(f"Missing {key}")
        return match.group(1).strip()
