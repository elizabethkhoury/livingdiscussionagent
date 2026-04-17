from src.domain.enums import CommercialOpportunity
from src.domain.models import ThreadContext
from src.domain.policies import prompthunt_eligible


class CommercialFitClassifier:
    def score(self, thread: ThreadContext):
        text = thread.combined_text.lower()
        if prompthunt_eligible(text):
            return 0.82, CommercialOpportunity.HIGH
        if any(token in text for token in ["tool", "tools", "workflow", "save prompts", "prompt repo"]):
            return 0.61, CommercialOpportunity.MEDIUM
        return 0.2, CommercialOpportunity.LOW

