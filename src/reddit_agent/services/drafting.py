from __future__ import annotations

from sqlalchemy import select

from reddit_agent.models import Draft, RedditCandidate
from reddit_agent.repository import Repository


def similarity_score(draft: str, prior_drafts: list[str]):
    if not prior_drafts:
        return 0.0
    draft_terms = set(draft.lower().split())
    overlaps = []
    for previous in prior_drafts:
        previous_terms = set(previous.lower().split())
        union = draft_terms | previous_terms
        overlaps.append(len(draft_terms & previous_terms) / max(1, len(union)))
    return round(max(overlaps), 3)


class DraftingService:
    def __init__(self, llm_provider):
        self.llm_provider = llm_provider

    async def generate(self, *, repository: Repository, candidate: RedditCandidate):
        if not candidate.route_product:
            raise ValueError('Candidate has no routed product.')
        result = await self.llm_provider.generate_draft(
            title=candidate.title,
            body=candidate.body,
            subreddit=candidate.subreddit,
            route_product=candidate.route_product,
        )
        critic = await self.llm_provider.critic_pass(
            draft=result.body,
            route_product=candidate.route_product,
            subreddit=candidate.subreddit,
        )
        prior_rows = await repository.session.execute(select(Draft.body))
        prior_bodies = list(prior_rows.scalars())
        similarity = similarity_score(result.body, prior_bodies)
        draft = await repository.create_draft(
            candidate.id,
            result.body,
            critic.notes,
            result.token_usage + critic.token_usage,
            similarity,
        )
        await repository.session.commit()
        await repository.session.refresh(draft)
        return draft
