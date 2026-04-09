from __future__ import annotations

from reddit_agent.clients.reddit import RedditClient
from reddit_agent.repository import Repository
from reddit_agent.rules import (
    ProductRule,
    SubredditRule,
    detect_safety_block,
    route_product,
    should_queue,
)


class DiscoveryService:
    def __init__(self, reddit_client: RedditClient, llm_provider, lifecycle_rules):
        self.reddit_client = reddit_client
        self.llm_provider = llm_provider
        self.lifecycle_rules = lifecycle_rules

    async def sync_subreddit(
        self,
        *,
        repository: Repository,
        subreddit_rule: SubredditRule,
        product_rules: dict[str, ProductRule],
    ):
        created = []
        for payload in await self.reddit_client.fetch_new_posts(subreddit_rule.name):
            text = f'{payload["title"]} {payload["body"]}'.strip()
            safety_reason = detect_safety_block(text)
            route = route_product(text)
            evaluation = await self.llm_provider.evaluate_candidate(
                title=payload['title'],
                body=payload['body'],
                route_product=route,
            )
            expected_value = (
                evaluation.relevance_score * 0.45
                + evaluation.replyability_score * 0.35
                + evaluation.promo_fit_score * 0.4
                - evaluation.risk_score * 0.4
            )
            decision = 'watch_only'
            abstain_reason = None
            if not subreddit_rule.allow_promotion and route is not None:
                decision = 'abstain'
                abstain_reason = 'subreddit_disallows_promotion'
                route = None
            elif safety_reason:
                decision = 'abstain'
                abstain_reason = safety_reason
                route = None
            elif route is None:
                decision = 'abstain'
                abstain_reason = 'no_product_fit'
            elif should_queue(
                evaluation.confidence, evaluation.risk_score, expected_value, self.lifecycle_rules
            ):
                decision = 'queue_draft'
            trace = {
                'subreddit_rule': subreddit_rule.notes,
                'route_product': route,
                'decision_reason': abstain_reason or 'threshold_pass',
                'evaluation_summary': evaluation.summary,
                'product_catalog': list(product_rules),
            }
            candidate = await repository.create_candidate(
                {
                    **payload,
                    'route_product': route,
                    'decision': decision,
                    'abstain_reason': abstain_reason,
                    'evaluator_summary': evaluation.summary,
                    'model_confidence': evaluation.confidence,
                    'risk_score': evaluation.risk_score,
                    'expected_value': round(expected_value, 3),
                },
                trace,
            )
            await repository.add_features(
                candidate.id,
                {
                    'relevance_score': evaluation.relevance_score,
                    'replyability_score': evaluation.replyability_score,
                    'promo_fit_score': evaluation.promo_fit_score,
                    'risk_score': evaluation.risk_score,
                    'uncertainty_score': evaluation.uncertainty_score,
                    'freshness_score': max(0.05, 1 - min(payload['freshness_hours'], 12) / 12),
                    'competition_score': min(1.0, payload['num_comments'] / 100),
                    'token_cost_estimate': 128,
                    'feature_payload': {
                        'depth_score': evaluation.depth_score,
                        'subreddit_tags': subreddit_rule.tags,
                    },
                },
            )
            if decision == 'queue_draft':
                await repository.create_action(
                    candidate.id, 'queued', notes='Candidate queued for drafting.'
                )
            created.append(candidate)
        await repository.session.commit()
        return created
