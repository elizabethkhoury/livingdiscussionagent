from src.domain.enums import ResponseStrategy


def _enum_value(value):
    return value if isinstance(value, str) else value.value


def build_learning_features(classification, draft):
    promotion_mode = getattr(draft, "promotion_mode", None)
    if promotion_mode is None and getattr(draft, "decision", None) is not None:
        promotion_mode = draft.decision.promotion_mode

    return {
        "intent": classification.intent,
        "relevance_score": classification.relevance_score,
        "value_add_score": classification.value_add_score,
        "policy_risk_score": classification.policy_risk_score,
        "promo_fit_score": classification.promo_fit_score,
        "strategy": _enum_value(draft.strategy),
        "promotion_mode": _enum_value(promotion_mode),
    }


def default_strategy_weights():
    return {
        ResponseStrategy.EDUCATIONAL.value: 1.0,
        ResponseStrategy.COMPARATIVE.value: 1.0,
        ResponseStrategy.EXPERIENTIAL.value: 1.0,
        ResponseStrategy.RESOURCE_LINKING.value: 1.0,
    }
