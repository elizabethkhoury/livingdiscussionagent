from src.domain.models import EngagementSnapshot


def classify_negative_signal(snapshot: EngagementSnapshot):
    if snapshot.is_removed:
        return "moderator_removal"
    if snapshot.is_deleted:
        return "deleted"
    if snapshot.score < 0:
        return "strong_negative_reply_signal"
    return "healthy"

