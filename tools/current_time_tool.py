from datetime import datetime

class CurrentTimeTool:
    name = "current_time"
    description = "현재 시간 조회"

    def run(self, tool_input: str) -> str:
        return datetime.now().isoformat(timespec="seconds")
