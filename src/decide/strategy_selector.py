from src.domain.enums import IntentType, ResponseStrategy


class StrategySelector:
    def select(self, intent: str):
        if intent == IntentType.COMPARISON.value:
            return ResponseStrategy.COMPARATIVE
        if intent == IntentType.RECOMMENDATION_REQUEST.value:
            return ResponseStrategy.RESOURCE_LINKING
        if intent == IntentType.COMPLAINT.value:
            return ResponseStrategy.EXPERIENTIAL
        return ResponseStrategy.EDUCATIONAL

