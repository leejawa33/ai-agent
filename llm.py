import os
import json
import logging
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

OPENAI_MODEL = "gpt-4o-mini"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("agent.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

class OpenAILLM:
    def __init__(self):
        self.aclient = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def acall(self, messages, tools, recorder=None) -> dict:
        logger.debug("▶ REQUEST\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        t0 = time.time()
        res = await self.aclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
            temperature=0,
            parallel_tool_calls=False,
        )
        latency_ms = (time.time() - t0) * 1000
        result = self._to_dict(res.choices[0].message)
        if recorder is not None and res.usage is not None:
            recorder.record_llm(
                model=OPENAI_MODEL,
                input_tokens=res.usage.prompt_tokens,
                output_tokens=res.usage.completion_tokens,
                latency_ms=latency_ms,
                request_summary={"messages_count": len(messages), "tools_count": len(tools)},
                response_summary=result,
            )
        logger.debug("◀ RESPONSE\n%s", json.dumps(result, ensure_ascii=False, indent=2))
        return result

    async def astream_call(self, messages, tools, recorder=None):
        logger.debug("▶ REQUEST (stream)\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        t0 = time.time()
        stream = await self.aclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
            temperature=0,
            stream=True,
            parallel_tool_calls=False,
            stream_options={"include_usage": True},
        )
        full_content = ""
        tool_calls_accum = {}
        usage = None

        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                full_content += delta.content
                yield ("token", delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_accum:
                        tool_calls_accum[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_accum[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_accum[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_accum[idx]["arguments"] += tc.function.arguments
                            yield ("tool_token", tc.function.arguments)

        if tool_calls_accum:
            tool_calls = [
                {
                    "id": v["id"],
                    "type": "function",
                    "function": {"name": v["name"], "arguments": v["arguments"]}
                }
                for v in tool_calls_accum.values()
            ]
            result = {"role": "assistant", "content": full_content or None, "tool_calls": tool_calls}
        else:
            result = {"role": "assistant", "content": full_content, "tool_calls": None}

        logger.debug("◀ RESPONSE (stream)\n%s", json.dumps(result, ensure_ascii=False, indent=2))
        if recorder is not None and usage is not None:
            latency_ms = (time.time() - t0) * 1000
            recorder.record_llm(
                model=OPENAI_MODEL,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                latency_ms=latency_ms,
                request_summary={"messages_count": len(messages), "tools_count": len(tools), "stream": True},
                response_summary=result,
            )
        yield ("done", result)

    def _to_dict(self, message) -> dict:
        d = {"role": message.role, "content": message.content}
        if message.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in message.tool_calls
            ]
        return d
