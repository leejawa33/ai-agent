import re

class ReActAgent:
    def __init__(self, llm, tools: dict, system_prompt: str):
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

    def run(self, user_input: str, max_steps: int = 5):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

        steps = []

        for step in range(1, max_steps + 1):
            response = self.llm.call(messages)

            thought = self._parse("Thought", response)
            action = self._parse("Action", response)

            step_log = {
                "step": step,
                "thought": thought,
                "action": action,
                "tool": None,
                "observation": None,
            }

            if action == "final":
                step_log["final"] = self._parse("Output", response)
                steps.append(step_log)
                return step_log["final"], steps

            tool_name = self._parse("ToolName", response)
            tool_input = self._parse("Input", response)

            tool = self.tools.get(tool_name)
            observation = tool.run(tool_input) if tool else "Tool not found"

            step_log["tool"] = tool_name
            step_log["observation"] = observation
            steps.append(step_log)

            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": f"Observation: {observation}"
            })

        raise Exception("Max steps exceeded")

    def _parse(self, key: str, text: str) -> str:
        match = re.search(rf"{key}:\s*(.*)", text)
        if not match:
            raise Exception(f"Missing {key}")
        return match.group(1).strip()
