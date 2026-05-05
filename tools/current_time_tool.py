from datetime import datetime

from .base import tool


@tool(description="현재 시간을 조회합니다")
def current_time() -> str:
    return datetime.now().isoformat(timespec="seconds")
