"""Posting-window gate.

Restricts when the bot is allowed to *post* (primary replies + follow-ups).
Ingest, monitor, and the shadowban canary still run outside the window — only
the actual public-facing posting is gated. Posting at 3am UTC is one of the
clearest bot signals; restricting to peak hours makes each post visible to
more readers and looks more human.
"""

from __future__ import annotations

from datetime import datetime

from src.app.settings import get_settings


def is_within_active_hours(now: datetime | None = None) -> bool:
    """Returns True if the current UTC hour is inside the configured posting window.

    The window wraps midnight: e.g. start=14, end=6 means "post between 14:00 UTC
    today and 06:00 UTC tomorrow". If start == end, posting is always allowed
    (treat as "always-on").
    """
    settings = get_settings()
    start = settings.active_hours_utc_start
    end = settings.active_hours_utc_end
    if start == end:
        return True  # No restriction
    hour = (now or datetime.utcnow()).hour
    if start < end:
        return start <= hour < end
    # Wraps midnight (start > end): active is [start..23] U [0..end-1]
    return hour >= start or hour < end


def hours_until_active(now: datetime | None = None) -> float:
    """Returns hours until the next active-window start (0.0 if currently active)."""
    if is_within_active_hours(now):
        return 0.0
    settings = get_settings()
    start = settings.active_hours_utc_start
    n = now or datetime.utcnow()
    if n.hour < start:
        return start - n.hour - (n.minute / 60.0)
    return (24 - n.hour) + start - (n.minute / 60.0)
