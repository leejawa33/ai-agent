from openai import OpenAI

class OpenAILLM:
    def __init__(self):
        self.client = OpenAI()

    def call(self, messages):
        res = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
        )
        return res.choices[0].message.content