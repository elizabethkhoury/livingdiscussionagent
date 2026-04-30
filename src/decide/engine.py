from __future__ import annotations

from src.app.config import get_default_thresholds
from src.decide.strategy_selector import StrategySelector
from src.domain.enums import DecisionAction, PromotionMode, RiskLevel, SubredditPromoPolicy
from src.domain.models import ClassificationResult, DecisionResult, MemoryContext, PolicyDecisionTrace, ThreadContext
from src.domain.policies import prompthunt_eligible
from src.learn.memory_provider import MemoryProvider


class RuleBasedDecisionEngine:
    def __init__(self, memory_provider: MemoryProvider | None = None):
        self.thresholds = get_default_thresholds()
        self.strategy_selector = StrategySelector()
        self.memory_provider = memory_provider or MemoryProvider()

    def decide(self, thread: ThreadContext, classification: ClassificationResult):
        memory_context = self.memory_provider.get_context()
        strategy = self._select_strategy(classification.intent, memory_context)
        trace = PolicyDecisionTrace(
            thresholds=self.thresholds.model_dump(),
            classifier_summary={
                "relevance_score": classification.relevance_score,
                "value_add_score": classification.value_add_score,
                "policy_risk_score": classification.policy_risk_score,
                "promo_fit_score": classification.promo_fit_score,
                "duplicate_similarity_score": classification.duplicate_similarity_score,
                "memory_context": self._memory_summary(memory_context),
            },
        )
        memory_reason = self._memory_strategy_reason(memory_context)
        if memory_reason:
            trace.reason_codes.append(memory_reason)
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
        if self._memory_requires_review(memory_context):
            trace.reason_codes.append("memory_caution_requires_review")
            return DecisionResult(
                action=DecisionAction.QUEUE_REVIEW_RISKY,
                promotion_mode=PromotionMode.NONE,
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

    def _select_strategy(self, intent: str, memory_context: MemoryContext):
        if self._memory_prefers_comparative(memory_context):
            return self.strategy_selector.select("comparison")
        return self.strategy_selector.select(intent)

    def _memory_prefers_comparative(self, memory_context: MemoryContext):
        memory_text = memory_context.prompt_text.lower()
        return "prefer comparative" in memory_text or "favor educational and comparative" in memory_text

    def _memory_strategy_reason(self, memory_context: MemoryContext):
        if self._memory_prefers_comparative(memory_context):
            return "memory_prefers_comparative_strategy"
        return None

    def _memory_requires_review(self, memory_context: MemoryContext):
        removals = sum(int(entry.metrics.get("removals", 0)) for entry in memory_context.daily_entries)
        negative_rewards = sum(int(entry.metrics.get("negative_rewards", 0)) for entry in memory_context.daily_entries)
        rewards = [
            float(entry.metrics.get("average_reward", 0.0))
            for entry in memory_context.daily_entries
            if int(entry.metrics.get("learning_examples", 0)) > 0
        ]
        low_average_reward = bool(rewards) and (sum(rewards) / len(rewards)) < 0.25
        return removals > 0 or negative_rewards >= 3 or low_average_reward

    def _memory_summary(self, memory_context: MemoryContext):
        if not memory_context.daily_entries and not memory_context.monthly_recaps:
            return "none"
        latest_entry = memory_context.daily_entries[0] if memory_context.daily_entries else None
        latest_recap = memory_context.monthly_recaps[0] if memory_context.monthly_recaps else None
        parts = [
            f"daily_entries={len(memory_context.daily_entries)}",
            f"monthly_recaps={len(memory_context.monthly_recaps)}",
        ]
        if latest_entry:
            parts.append(f"latest_lesson={latest_entry.what_i_learned}")
        if latest_recap:
            parts.append(f"latest_recap={latest_recap.summary}")
        return "; ".join(parts)
