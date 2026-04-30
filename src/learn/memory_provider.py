from __future__ import annotations

from pathlib import Path

from src.app.settings import get_settings
from src.domain.models import MemoryContext
from src.learn.diary_memory import load_memory_context
from src.storage.db import session_scope
from src.storage.repositories import LearningRepository


class MemoryProvider:
    def __init__(self, diary_path: Path | None = None, enabled: bool | None = None, recent_days: int | None = None, recap_months: int | None = None):
        settings = get_settings()
        self.diary_path = diary_path or Path(settings.memory_diary_path)
        self.enabled = settings.memory_enabled if enabled is None else enabled
        self.recent_days = recent_days or settings.memory_recent_days
        self.recap_months = recap_months or settings.memory_monthly_recap_months

    def get_context(self):
        if not self.enabled:
            return MemoryContext()
        if not self.diary_path.exists():
            return MemoryContext()
        try:
            return load_memory_context(self.diary_path, self.recent_days, self.recap_months)
        except Exception as exc:
            self._log_failure(exc)
            return MemoryContext()

    def prompt_text(self):
        return self.get_context().prompt_text

    def _log_failure(self, exc: Exception):
        try:
            with session_scope() as session:
                LearningRepository(session).log_event(
                    "memory_load_failed",
                    {
                        "diary_path": str(self.diary_path),
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )
        except Exception:
            return None
        return None
