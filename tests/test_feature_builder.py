from src.learn.feature_builder import build_learning_features
from src.storage import schema


def test_build_learning_features_uses_decision_promotion_mode_for_draft_records():
    classification = schema.ClassificationRecord(
        intent="question",
        relevance_score=0.9,
        value_add_score=0.8,
        policy_risk_score=0.1,
        promo_fit_score=0.7,
    )
    decision = schema.DecisionRecord(promotion_mode="none")
    draft = schema.DraftRecord(strategy="educational", decision=decision)

    features = build_learning_features(classification, draft)

    assert features["promotion_mode"] == "none"
    assert features["strategy"] == "educational"
