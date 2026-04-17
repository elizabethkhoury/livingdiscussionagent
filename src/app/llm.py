from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

from src.app.settings import get_settings


@dataclass
class LLMMessage:
    role: str
    content: str


class LLMClient:
    def complete(self, messages: list[LLMMessage], temperature: float = 0.2) -> str:
        raise NotImplementedError


class HeuristicLLMClient(LLMClient):
    def complete(self, messages: list[LLMMessage], temperature: float = 0.2) -> str:
        return messages[-1].content


class MistralLLMClient(LLMClient):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(self, messages: list[LLMMessage], temperature: float = 0.2) -> str:
        payload = json.dumps(
            {
                "model": "mistral-small-latest",
                "temperature": temperature,
                "messages": [{"role": item.role, "content": item.content} for item in messages],
            }
        ).encode("utf-8")
        req = request.Request(
            url="https://api.mistral.ai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()


def get_llm_client():
    settings = get_settings()
    if settings.llm_provider == "mistral" and settings.llm_api_key:
        return MistralLLMClient(settings.llm_api_key)
    return HeuristicLLMClient()

