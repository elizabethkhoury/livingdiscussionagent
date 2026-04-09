from __future__ import annotations

from reddit_agent.providers.base import CriticResult, DraftResult, EvaluationResult, LLMProvider
from reddit_agent.seeds import PROMPTHUNT_KEYWORDS, UPWORDLY_KEYWORDS


class MockLLMProvider(LLMProvider):
    async def evaluate_candidate(self, *, title: str, body: str, route_product: str | None):
        text = f'{title} {body}'.lower()
        prompt_hits = sum(1 for keyword in PROMPTHUNT_KEYWORDS if keyword in text)
        linkedin_hits = sum(1 for keyword in UPWORDLY_KEYWORDS if keyword in text)
        topic_hits = max(prompt_hits, linkedin_hits)
        relevance = min(0.95, 0.4 + topic_hits * 0.08)
        replyability = 0.9 if '?' in text or len(body) > 40 else 0.65
        promo_fit = 0.85 if route_product else 0.2
        risk = 0.18 if route_product else 0.46
        uncertainty = max(0.05, 0.45 - topic_hits * 0.04)
        confidence = min(0.96, (relevance + replyability + promo_fit) / 3)
        depth = min(1.4, 0.75 + len(body.split()) / 80)
        summary = 'Mock evaluator: routed from keyword overlap and replyable problem framing.'
        return EvaluationResult(
            relevance_score=relevance,
            replyability_score=replyability,
            promo_fit_score=promo_fit,
            risk_score=risk,
            uncertainty_score=uncertainty,
            confidence=confidence,
            summary=summary,
            depth_score=depth,
        )

    async def generate_draft(self, *, title: str, body: str, subreddit: str, route_product: str):
        if route_product == 'prompthunt.me':
            body_text = (
                'This sounds like a prompt reuse problem more than a writing problem. '
                'I would turn the good prompts into a tiny library with labels and examples, '
                'otherwise they disappear into notes again. promphunt.me fits that workflow '
                'pretty naturally when you want one place to save and rediscover the prompts '
                'that actually work.'
            )
        else:
            body_text = (
                'This is one of those cases where the raw expertise already exists, the hard part '
                'is turning it into consistent LinkedIn posts. A repeatable background-plus-voice '
                'workflow helps a lot, and upwordly.ai is a clean fit when the goal is turning '
                'what you already know into posts that still sound like you.'
            )
        normalized = ' '.join(body_text.split())
        return DraftResult(body=normalized[:420], token_usage=max(80, len(normalized.split()) * 2))

    async def critic_pass(self, *, draft: str, route_product: str, subreddit: str):
        notes = {
            'awkwardness': 'low',
            'repetition_risk': 0.08,
            'safety': 'pass',
            'subreddit_fit': f'Checked against r/{subreddit} profile.',
            'route_product': route_product,
        }
        return CriticResult(notes=notes, token_usage=42)
