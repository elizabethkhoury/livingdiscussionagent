from __future__ import annotations

from src.app.settings import get_settings
from src.domain.enums import PromotionMode

PROMPTHUNT_ELIGIBILITY_SIGNALS = [
    "save prompts",
    "organize prompts",
    "find prompts",
    "reuse prompts",
    "prompt library",
    "prompt libraries",
    "prompt repository",
    "shared prompts",
    "rewrite the same prompt",
    "losing prompts",
]

PROMPTHUNT_BLOCK_SIGNALS = [
    "lawsuit",
    "pricing",
    "hiring",
    "job",
    "meme",
    "earnings",
    "drama",
]

BANNED_HYPE_PHRASES = [
    "best",
    "amazing",
    "must-have",
    "game changer",
]


def prompthunt_eligible(text: str):
    lower = text.lower()
    if any(signal in lower for signal in PROMPTHUNT_BLOCK_SIGNALS):
        return False
    if "prompt" in lower and "save" in lower:
        return True
    if "prompt" in lower and "reuse" in lower:
        return True
    if "prompt" in lower and "find" in lower:
        return True
    return any(signal in lower for signal in PROMPTHUNT_ELIGIBILITY_SIGNALS)


def monetized_disclosure_required(body: str):
    settings = get_settings()
    lower = body.lower()
    has_domain = any(domain.lower() in lower for domain in settings.monetized_link_domains)
    has_tracking = any(token in lower for token in ["utm_", "ref=", "affiliate", "coupon", "code "])
    return has_domain and has_tracking


def allowed_first_person():
    return get_settings().first_person_claims_allowed


def validate_promotion_mode(mode: PromotionMode, body: str):
    if mode == PromotionMode.DISCLOSED_MONETIZED and not monetized_disclosure_required(body):
        return False
    return True
