import re

class CalculatorTool:
    name = "calculator"
    schema = {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "수학 계산식을 실행합니다",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "계산할 수식 (예: 12*3+4)"}
                },
                "required": ["expression"]
            }
        }
    }

    def run(self, tool_input: str) -> str:
        if not re.fullmatch(r"[0-9+\-*/().\s]+", tool_input):
            return "ERROR: invalid expression"
        return str(eval(tool_input, {"__builtins__": {}}))
