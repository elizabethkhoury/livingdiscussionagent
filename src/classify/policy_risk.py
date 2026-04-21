from src.domain.enums import SubredditPromoPolicy
from src.domain.models import ThreadContext

RISKY_THREAD_SIGNALS = [
    "rules",
    "mods",
    "self promo",
    "promotion",
    "affiliate",
    "report",
    "spam",
    "meme",
]


class PolicyRiskClassifier:
    def score(self, thread: ThreadContext, promo_policy: SubredditPromoPolicy):
        text = thread.combined_text.lower()
        score = 0.05
        if promo_policy == SubredditPromoPolicy.REVIEW_ONLY:
            score += 0.25
        if promo_policy == SubredditPromoPolicy.DENY:
            score += 0.5
        if any(signal in text for signal in RISKY_THREAD_SIGNALS):
            score += 0.2
        if thread.post.age_hours > 24:
            score += 0.1
        return min(score, 1.0)
