from src.app.settings import get_settings
from src.domain.enums import PromotionMode


def disclosure_for_mode(mode: PromotionMode):
    if mode == PromotionMode.DISCLOSED_MONETIZED:
        return get_settings().default_disclosure_template
    return None
