from enum import StrEnum


class IntentType(StrEnum):
    QUESTION = "question"
    COMPLAINT = "complaint"
    COMPARISON = "comparison"
    RECOMMENDATION_REQUEST = "recommendation_request"
    DISCUSSION = "discussion"
    SHOWCASE = "showcase"
    NEWS = "news"
    JOB_POSTING = "job_posting"
    OTHER = "other"


class DecisionAction(StrEnum):
    SKIP = "skip"
    AUTOPOST_INFO = "autopost_info"
    QUEUE_REVIEW_PRODUCT = "queue_review_product"
    QUEUE_REVIEW_RISKY = "queue_review_risky"
    QUEUE_REVIEW_LOW_CONFIDENCE = "queue_review_low_confidence"


class ResponseStrategy(StrEnum):
    EDUCATIONAL = "educational"
    COMPARATIVE = "comparative"
    EXPERIENTIAL = "experiential"
    RESOURCE_LINKING = "resource_linking"


class PromotionMode(StrEnum):
    NONE = "none"
    PLAIN_MENTION = "plain_mention"
    DISCLOSED_MONETIZED = "disclosed_monetized"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCK = "block"


class Tone(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    FRUSTRATED = "frustrated"
    SKEPTICAL = "skeptical"
    NEUTRAL = "neutral"


class CommercialOpportunity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SubredditPromoPolicy(StrEnum):
    ALLOW = "allow"
    REVIEW_ONLY = "review_only"
    DENY = "deny"


class DraftStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    REJECTED = "rejected"
    POSTED = "posted"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AttemptStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
