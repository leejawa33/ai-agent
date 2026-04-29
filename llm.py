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