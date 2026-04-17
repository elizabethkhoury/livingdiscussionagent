from __future__ import annotations

from src.app.config import get_default_thresholds
from src.decide.strategy_selector import StrategySelector
from src.domain.enums import DecisionAction, PromotionMode, RiskLevel, SubredditPromoPolicy
from src.domain.models import ClassificationResult, DecisionResult, PolicyDecisionTrace, ThreadContext
from src.domain.policies import prompthunt_eligible


class RuleBasedDecisionEngine:
    def __init__(self):
        self.thresholds = get_default_thresholds()
        self.strategy_selector = StrategySelector()

    def decide(self, thread: ThreadContext, classification: ClassificationResult):
        trace = PolicyDecisionTrace(
            thresholds=self.thresholds.model_dump(),
            classifier_summary={
                "relevance_score": classification.relevance_score,
                "value_add_score": classification.value_add_score,
                "policy_risk_score": classification.policy_risk_score,
                "promo_fit_score": classification.promo_fit_score,
                "duplicate_similarity_score": classification.duplicate_similarity_score,
            },
        )
        strategy = self.strategy_selector.select(classification.intent)
        lower = thread.combined_text.lower()
        blocked_signals = ["meme", "job posting", "lawsuit", "earnings", "locked"]
        if any(signal in lower for signal in blocked_signals):
            trace.blocked = True
            trace.reason_codes.append("hard_block_signal")
            return DecisionResult(
                action=DecisionAction.SKIP,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.BLOCK,
                selected_strategy=strategy,
                trace=trace,
            )
        if classification.subreddit_promo_policy == SubredditPromoPolicy.DENY:
            trace.reason_codes.append("promo_denied_by_subreddit")
        if classification.relevance_score < self.thresholds.relevance_threshold:
            trace.reason_codes.append("relevance_below_threshold")
            return DecisionResult(
                action=DecisionAction.SKIP,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.LOW,
                selected_strategy=strategy,
                trace=trace,
            )
        if classification.value_add_score < self.thresholds.value_add_threshold:
            trace.reason_codes.append("value_add_below_threshold")
            return DecisionResult(
                action=DecisionAction.SKIP,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.LOW,
                selected_strategy=strategy,
                trace=trace,
            )
        if classification.duplicate_similarity_score > 0.92:
            trace.reason_codes.append("duplicate_similarity_too_high")
            return DecisionResult(
                action=DecisionAction.SKIP,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.LOW,
                selected_strategy=strategy,
                trace=trace,
            )
        if classification.intent == "discussion" and classification.value_add_score < 0.80:
            trace.reason_codes.append("discussion_without_clear_value")
            return DecisionResult(
                action=DecisionAction.SKIP,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.LOW,
                selected_strategy=strategy,
                trace=trace,
            )
        if classification.policy_risk_score >= 0.55:
            trace.reason_codes.append("policy_risk_requires_review")
            return DecisionResult(
                action=DecisionAction.QUEUE_REVIEW_RISKY,
                promotion_mode=PromotionMode.NONE,
                requires_review=True,
                risk_level=RiskLevel.HIGH,
                selected_strategy=strategy,
                trace=trace,
            )

        promo_eligible = (
            classification.subreddit_promo_policy != SubredditPromoPolicy.DENY
            and classification.promo_fit_score >= 0.75
            and classification.commercial_opportunity.value == "high"
            and prompthunt_eligible(thread.combined_text)
        )
        if promo_eligible:
            trace.reason_codes.append("product_review_required")
            return DecisionResult(
                action=DecisionAction.QUEUE_REVIEW_PRODUCT,
                promotion_mode=PromotionMode.PLAIN_MENTION,
                requires_review=True,
                risk_level=RiskLevel.MEDIUM,
                selected_strategy=strategy,
                trace=trace,
            )
        trace.reason_codes.append("autopost_information_only")
        return DecisionResult(
            action=DecisionAction.AUTOPOST_INFO,
            promotion_mode=PromotionMode.NONE,
            requires_review=False,
            risk_level=RiskLevel.LOW,
            selected_strategy=strategy,
            trace=trace,
        )

