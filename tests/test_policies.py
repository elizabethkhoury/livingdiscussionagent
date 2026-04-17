from src.domain.enums import PromotionMode
from src.domain.policies import monetized_disclosure_required, prompthunt_eligible, validate_promotion_mode


def test_prompt_library_request_is_eligible():
    assert prompthunt_eligible("Where can I save and reuse my best prompts?") is True


def test_news_thread_is_not_eligible():
    assert prompthunt_eligible("OpenAI pricing drama and earnings chatter") is False


def test_monetized_body_requires_disclosure():
    body = "PromptHunt could help here: https://prompthunt.me?utm_source=reddit"
    assert monetized_disclosure_required(body) is True
    assert validate_promotion_mode(PromotionMode.DISCLOSED_MONETIZED, body) is True
