"""LLM-as-judge — 비결정론적 답변(시간, 위키 요약 등)을 criteria 기준으로 채점하는 채점 LLM.

결정론적 케이스(계산 결과)는 runner의 contains 매칭이 담당하고,
judge는 문자열 매칭으로 판정 불가능한 케이스만 맡는다 (비용 최소화).
"""
import json
import os

from openai import AsyncOpenAI

JUDGE_MODEL = "gpt-4o-mini"

# JSON mode(response_format=json_object)는 프롬프트에 'json' 언급이 필수
JUDGE_SYSTEM = """\
너는 AI 에이전트의 답변을 채점하는 채점관이다.
사용자 질문, 에이전트의 답변, 채점 기준이 주어진다.
채점 기준만으로 판정하라. 답변의 문체·길이·친절함은 채점 대상이 아니다.
반드시 아래 형식의 JSON으로만 응답하라:
{"correct": true 또는 false, "reason": "판정 근거 한 문장"}
"""


class Judge:
    """채점 호출을 누적 추적 (토큰/비용은 runner 리포트에 포함)."""

    def __init__(self, model: str = JUDGE_MODEL):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.call_count = 0
        self.input_tokens = 0
        self.output_tokens = 0

    async def grade(self, question: str, answer: str, criteria: str) -> dict:
        user_msg = (
            f"[사용자 질문]\n{question}\n\n"
            f"[에이전트 답변]\n{answer}\n\n"
            f"[채점 기준]\n{criteria}"
        )
        res = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        self.call_count += 1
        if res.usage:
            self.input_tokens += res.usage.prompt_tokens
            self.output_tokens += res.usage.completion_tokens

        try:
            verdict = json.loads(res.choices[0].message.content)
            return {"correct": bool(verdict.get("correct")), "reason": str(verdict.get("reason", ""))}
        except (json.JSONDecodeError, AttributeError) as e:
            return {"correct": False, "reason": f"judge 응답 파싱 실패: {e}"}
