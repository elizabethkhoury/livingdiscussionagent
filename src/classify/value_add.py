from src.domain.models import ThreadContext


class ValueAddClassifier:
    def score(self, thread: ThreadContext):
        text = thread.combined_text.lower()
        score = 0.45
        if "?" in text:
            score += 0.2
        if any(token in text for token in ["how", "why", "tips", "help", "fix", "issue", "problem"]):
            score += 0.2
        if any(token in text for token in ["meme", "shitpost", "lol"]):
            score -= 0.25
        if thread.target_comment:
            score += 0.05
        return max(0.0, min(score, 1.0))

