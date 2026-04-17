from src.domain.enums import IntentType, Tone
from src.domain.models import ThreadContext


class IntentClassifier:
    def classify(self, thread: ThreadContext):
        text = thread.combined_text.lower()
        if any(token in text for token in ["hiring", "job", "resume"]):
            return IntentType.JOB_POSTING, Tone.NEUTRAL
        if "?" in text or any(token in text for token in ["how do", "how can", "any tips", "what should"]):
            return IntentType.QUESTION, Tone.BEGINNER
        if any(token in text for token in ["vs", "compare", "comparison", "better than"]):
            return IntentType.COMPARISON, Tone.INTERMEDIATE
        if any(token in text for token in ["recommend", "looking for a tool", "where can i find"]):
            return IntentType.RECOMMENDATION_REQUEST, Tone.INTERMEDIATE
        if any(token in text for token in ["frustrated", "annoying", "hate", "keeps failing"]):
            return IntentType.COMPLAINT, Tone.FRUSTRATED
        if any(token in text for token in ["launched", "shipped", "showcase", "built"]):
            return IntentType.SHOWCASE, Tone.NEUTRAL
        if any(token in text for token in ["news", "announced", "update"]):
            return IntentType.NEWS, Tone.NEUTRAL
        return IntentType.DISCUSSION, Tone.NEUTRAL

