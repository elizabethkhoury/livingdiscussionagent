from __future__ import annotations

from src.classify.commercial_fit import CommercialFitClassifier
from src.classify.intent import IntentClassifier
from src.classify.policy_risk import PolicyRiskClassifier
from src.classify.relevance import RelevanceClassifier
from src.classify.value_add import ValueAddClassifier
from src.domain.models import ClassificationResult, ThreadContext
from src.ingest.subreddit_rules import subreddit_policy


class ClassificationPipeline:
    def __init__(self, duplicate_similarity_lookup=None):
        self.relevance = RelevanceClassifier()
        self.intent = IntentClassifier()
        self.commercial_fit = CommercialFitClassifier()
        self.policy_risk = PolicyRiskClassifier()
        self.value_add = ValueAddClassifier()
        self.duplicate_similarity_lookup = duplicate_similarity_lookup or (lambda _thread: 0.0)

    def classify(self, thread: ThreadContext):
        intent, tone = self.intent.classify(thread)
        promo_policy = subreddit_policy(thread.post.subreddit)
        promo_fit_score, commercial_opportunity = self.commercial_fit.score(thread)
        return ClassificationResult(
            intent=intent.value,
            relevance_score=self.relevance.score(thread),
            commercial_opportunity=commercial_opportunity,
            value_add_score=self.value_add.score(thread),
            policy_risk_score=self.policy_risk.score(thread, promo_policy),
            promo_fit_score=promo_fit_score,
            tone=tone,
            subreddit_promo_policy=promo_policy,
            duplicate_similarity_score=self.duplicate_similarity_lookup(thread),
            reason_codes=[],
        )
