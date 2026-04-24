from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import request

from src.app.settings import get_settings


@dataclass
class LLMMessage:
    role: str
    content: str


class LLMClient:
    def complete(self, messages: list[LLMMessage]) -> str:
        raise NotImplementedError


class HeuristicLLMClient(LLMClient):
    def complete(self, messages: list[LLMMessage]) -> str:
        return messages[-1].content


class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout_seconds: int, max_output_tokens: int):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    def complete(self, messages: list[LLMMessage]) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "max_output_tokens": self.max_output_tokens,
                "input": [
                    {
                        "role": item.role,
                        "content": [{"type": "input_text", "text": item.content}],
                    }
                    for item in messages
                ],
            }
        ).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/responses",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        return _extract_output_text(body)


def _extract_output_text(response_body: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for item in response_body.get("output", []):
        if item.get("type") != "message":
            continue
        for content_item in item.get("content", []):
            content_type = content_item.get("type")
            if content_type in {"output_text", "text"}:
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
    return "\n".join(text_parts).strip()


def get_llm_client():
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAILLMClient(
            settings.openai_api_key,
            settings.llm_model,
            settings.openai_timeout_seconds,
            settings.openai_max_output_tokens,
        )
    return HeuristicLLMClient()
