from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class EvaluationResult:
    relevance_score: float
    replyability_score: float
    promo_fit_score: float
    risk_score: float
    uncertainty_score: float
    confidence: float
    summary: str
    depth_score: float


@dataclass(slots=True)
class DraftResult:
    body: str
    token_usage: int


@dataclass(slots=True)
class CriticResult:
    notes: dict[str, str | float]
    token_usage: int


class LLMProvider(Protocol):
    async def evaluate_candidate(
        self, *, title: str, body: str, route_product: str | None
    ) -> EvaluationResult: ...

    async def generate_draft(
        self,
        *,
        title: str,
        body: str,
        subreddit: str,
        route_product: str,
    ) -> DraftResult: ...

    async def critic_pass(
        self, *, draft: str, route_product: str, subreddit: str
    ) -> CriticResult: ...
