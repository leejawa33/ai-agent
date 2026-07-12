import re

from pydantic import BaseModel, Field

from .base import tool


class CalculatorArgs(BaseModel):
    expression: str = Field(..., description="계산할 수식 (예: 12*3+4)")


@tool(CalculatorArgs, description="수학 계산식을 실행합니다")
def calculator(expression: str) -> str:
    if not re.fullmatch(r"[0-9+\-*/().\s]+", expression):
        return "ERROR: invalid expression"
    try:
        return str(eval(expression, {"__builtins__": {}}))
    except ZeroDivisionError:
        return "ERROR: division by zero"
    except Exception as e:
        return f"ERROR: {e}"
