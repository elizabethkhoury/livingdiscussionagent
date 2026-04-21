from src.domain.enums import ResponseStrategy


def build_learning_features(classification, draft):
    return {
        "intent": classification.intent,
        "relevance_score": classification.relevance_score,
        "value_add_score": classification.value_add_score,
        "policy_risk_score": classification.policy_risk_score,
        "promo_fit_score": classification.promo_fit_score,
        "strategy": draft.strategy if isinstance(draft.strategy, str) else draft.strategy.value,
        "promotion_mode": draft.promotion_mode if isinstance(draft.promotion_mode, str) else draft.promotion_mode.value,
    }


def default_strategy_weights():
    return {
        ResponseStrategy.EDUCATIONAL.value: 1.0,
        ResponseStrategy.COMPARATIVE.value: 1.0,
        ResponseStrategy.EXPERIENTIAL.value: 1.0,
        ResponseStrategy.RESOURCE_LINKING.value: 1.0,
    }
