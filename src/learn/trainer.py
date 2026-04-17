from __future__ import annotations

from statistics import mean

from src.app.config import get_default_thresholds
from src.domain.models import LearningUpdateReport
from src.learn.bounded_tuning import tune_threshold
from src.learn.feature_builder import default_strategy_weights
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, LearningRepository


class LearningTrainer:
    def update(self):
        with session_scope() as session:
            decisions = DecisionRepository(session)
            learning = LearningRepository(session)
            if decisions.recent_negative_signals(24) > 0:
                return LearningUpdateReport(updated=False, reason="frozen_due_to_recent_removal")
            examples = learning.recent_examples(7)
            if len(examples) < 30:
                return LearningUpdateReport(updated=False, reason="not_enough_examples")
            defaults = get_default_thresholds()
            avg_reward = mean(example.reward_score for example in examples)
            direction = 0.02 if avg_reward < 0.25 else -0.02 if avg_reward > 0.6 else 0.0
            thresholds = {
                "relevance_threshold": tune_threshold(defaults.relevance_threshold, direction, 0.60, 0.72),
                "value_add_threshold": tune_threshold(defaults.value_add_threshold, direction, 0.65, 0.80),
                "autopost_overall_threshold": tune_threshold(
                    defaults.autopost_overall_threshold, direction, 0.78, 0.86
                ),
            }
            weights = learning.latest_strategy_weights() or default_strategy_weights()
            weight_direction = 0.05 if avg_reward > 0.5 else -0.05
            updated_weights = {key: round(max(0.1, value + weight_direction), 2) for key, value in weights.items()}
            latest_version = learning.latest_strategy_version()
            learning.store_strategy_weights(latest_version + 1, updated_weights)
            learning.log_event("threshold_update", thresholds)
            return LearningUpdateReport(
                updated=True,
                reason="thresholds_and_weights_updated",
                strategy_weights=updated_weights,
                thresholds=thresholds,
            )
