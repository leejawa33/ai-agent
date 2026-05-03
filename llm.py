import os
import json
import logging
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI

load_dotenv()

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
        api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key)
        self.aclient = AsyncOpenAI(api_key=api_key)

    def call(self, messages, tools) -> dict:
        logger.debug("▶ REQUEST\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        res = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
            parallel_tool_calls=False,
        )
        result = self._to_dict(res.choices[0].message)
        logger.debug("◀ RESPONSE\n%s", json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def stream_call(self, messages, tools):
        logger.debug("▶ REQUEST (stream)\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        stream = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
            stream=True,
            parallel_tool_calls=False,
        )
        full_content = ""
        tool_calls_accum = {}

        for chunk in stream:
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
        yield ("done", result)

    async def acall(self, messages, tools) -> dict:
        logger.debug("▶ REQUEST (async)\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        res = await self.aclient.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
            parallel_tool_calls=False,
        )
        result = self._to_dict(res.choices[0].message)
        logger.debug("◀ RESPONSE (async)\n%s", json.dumps(result, ensure_ascii=False, indent=2))
        return result

    async def astream_call(self, messages, tools):
        logger.debug("▶ REQUEST (astream)\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
        stream = await self.aclient.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
            stream=True,
            parallel_tool_calls=False,
        )
        full_content = ""
        tool_calls_accum = {}

        async for chunk in stream:
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

        logger.debug("◀ RESPONSE (astream)\n%s", json.dumps(result, ensure_ascii=False, indent=2))
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
