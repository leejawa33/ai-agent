
import re

class CalculatorTool:
    name = "calculator"
    description = "수학 계산"

    def run(self, tool_input: str) -> str:
        if not re.fullmatch(r"[0-9+\-*/().\s]+", tool_input):
            return "ERROR: invalid expression"
        return str(eval(tool_input, {"__builtins__": {}}))


