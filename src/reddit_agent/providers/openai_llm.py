from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from reddit_agent.providers.base import CriticResult, DraftResult, EvaluationResult
from reddit_agent.settings import Settings


class EvaluationPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    relevance_score: float
    replyability_score: float
    promo_fit_score: float
    risk_score: float
    uncertainty_score: float
    confidence: float
    summary: str
    depth_score: float


class DraftPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    body: str


class CriticNotesPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    awkwardness: str
    repetition_risk: float
    safety: str
    subreddit_fit: str
    route_product: str


class OpenAILLMProvider:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError('OPENAI_API_KEY is required when LLM_MODE=openai.')

        client_kwargs: dict[str, Any] = {'api_key': settings.openai_api_key}
        if settings.openai_base_url:
            client_kwargs['base_url'] = settings.openai_base_url

        self.settings = settings
        self.client = AsyncOpenAI(**client_kwargs)

    async def evaluate_candidate(self, *, title: str, body: str, route_product: str | None):
        payload, _ = await self._structured_completion(
            model=self.settings.evaluator_model,
            schema_name='candidate_evaluation',
            schema_model=EvaluationPayload,
            system_prompt=(
                'You evaluate whether a Reddit thread is worth replying to for a '
                'compliance-first product recommendation workflow. Return calibrated scores '
                'between 0 and 1. Use higher risk scores for anything that looks spammy, '
                'unsafe, or promotion-hostile. Use higher promo_fit only when the routed '
                'product clearly and naturally fits the user need. Depth score should be '
                'between 0.5 and 1.5.'
            ),
            user_prompt=(
                f'Title: {title}\n'
                f'Body: {body}\n'
                f'Routed product: {route_product or "none"}\n\n'
                'Score the candidate and summarize the reasoning in 1-2 sentences.'
            ),
        )
        return EvaluationResult(**payload.model_dump())

    async def generate_draft(self, *, title: str, body: str, subreddit: str, route_product: str):
        payload, token_usage = await self._structured_completion(
            model=self.settings.generation_model,
            schema_name='reddit_draft',
            schema_model=DraftPayload,
            system_prompt=(
                'You write concise, natural Reddit replies for a compliance-first operator. '
                'Write a single comment that sounds helpful first and promotional second. '
                'Never claim affiliation, never fabricate personal experience, avoid hype, '
                'and keep it under 420 characters.'
            ),
            user_prompt=(
                f'Subreddit: r/{subreddit}\n'
                f'Routed product: {route_product}\n'
                f'Thread title: {title}\n'
                f'Thread body: {body}\n\n'
                'Write one reply that addresses the user need and mentions the routed product '
                'only if it fits naturally.'
            ),
        )
        normalized = ' '.join(payload.body.split())
        return DraftResult(body=normalized[:420], token_usage=token_usage)

    async def critic_pass(self, *, draft: str, route_product: str, subreddit: str):
        payload, token_usage = await self._structured_completion(
            model=self.settings.evaluator_model,
            schema_name='draft_critic_notes',
            schema_model=CriticNotesPayload,
            system_prompt=(
                'You are a strict Reddit reply critic. Judge clarity, repetition risk, and '
                'subreddit fit for a product mention workflow. Use concise notes and numeric '
                'repetition risk between 0 and 1.'
            ),
            user_prompt=(
                f'Subreddit: r/{subreddit}\n'
                f'Routed product: {route_product}\n'
                f'Draft: {draft}\n\n'
                'Review the draft and return structured notes.'
            ),
        )
        return CriticResult(notes=payload.model_dump(), token_usage=token_usage)

    async def _structured_completion(
        self,
        *,
        model: str,
        schema_name: str,
        schema_model: type[BaseModel],
        system_prompt: str,
        user_prompt: str,
    ):
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': schema_name,
                    'strict': True,
                    'schema': schema_model.model_json_schema(),
                },
            },
            **self._model_kwargs(model),
        )

        message = response.choices[0].message
        refusal = getattr(message, 'refusal', None)
        if refusal:
            raise RuntimeError(f'OpenAI refused structured output for {schema_name}: {refusal}')

        content = self._message_content(message.content)
        payload = schema_model.model_validate(json.loads(content))
        token_usage = response.usage.total_tokens if response.usage else 0
        return payload, token_usage

    def _model_kwargs(self, model: str):
        if model.startswith('gpt-5'):
            return {'reasoning_effort': 'medium', 'verbosity': 'medium'}
        return {}

    def _message_content(self, content: Any):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get('text')
                    if text:
                        text_parts.append(text)
                    continue
                text = getattr(item, 'text', None)
                if text:
                    text_parts.append(text)
            if text_parts:
                return ''.join(text_parts)
        raise RuntimeError('OpenAI returned no structured content.')
