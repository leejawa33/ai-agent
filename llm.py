import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class OpenAILLM:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def call(self, messages, tools) -> dict:
        res = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
        )
        return self._to_dict(res.choices[0].message)

    def stream_call(self, messages, tools):
        stream = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0,
            stream=True,
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
            yield ("done", {"role": "assistant", "content": full_content or None, "tool_calls": tool_calls})
        else:
            yield ("done", {"role": "assistant", "content": full_content, "tool_calls": None})

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
