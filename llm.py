import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class OpenAILLM:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def call(self, messages):
        res = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
        )
        return res.choices[0].message.content

    def stream_call(self, messages):
        stream = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
            stream=True,
        )
        full_text = ""
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                full_text += token
                yield token, full_text