from datetime import datetime

class CurrentTimeTool:
    name = "current_time"
    schema = {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "현재 시간을 조회합니다",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }

    def run(self, tool_input: str) -> str:
        return datetime.now().isoformat(timespec="seconds")
