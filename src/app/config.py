from src.app.settings import get_settings
from src.domain.models import RuntimeThresholds


def get_default_thresholds():
    settings = get_settings()
    return RuntimeThresholds(
        relevance_threshold=settings.relevance_threshold_default,
        value_add_threshold=settings.value_add_threshold_default,
        autopost_overall_threshold=settings.autopost_overall_threshold_default,
    )
