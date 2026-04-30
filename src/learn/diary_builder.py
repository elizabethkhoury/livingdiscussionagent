from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean

from src.app.settings import get_settings
from src.domain.models import DiaryEntry, MonthlyDiaryRecap
from src.learn.diary_memory import load_memory_context, upsert_daily_entry, upsert_monthly_recap
from src.storage.db import session_scope
from src.storage.repositories import LearningRepository


class DiaryBuilder:
    def __init__(self, diary_path: Path | None = None):
        settings = get_settings()
        self.diary_path = diary_path or Path(settings.memory_diary_path)

    def update(self, entry_date: date | None = None, force_monthly: bool = False):
        target_date = entry_date or date.today()
        with session_scope() as session:
            learning = LearningRepository(session)
            entry = build_daily_entry(learning, target_date)
        upsert_daily_entry(self.diary_path, entry)
        monthly_recap = self._maybe_update_monthly_recap(target_date, force_monthly)
        return {
            "diary_path": str(self.diary_path),
            "daily_entry_date": entry.date.isoformat(),
            "monthly_recap_month": monthly_recap.month if monthly_recap else None,
            "daily_metrics": entry.metrics,
        }

    def _maybe_update_monthly_recap(self, entry_date: date, force_monthly: bool):
        month = _recap_month_for(entry_date, force_monthly)
        if month is None:
            return None
        context = load_memory_context(self.diary_path, recent_days=370, recap_months=24)
        entries = [entry for entry in context.daily_entries if entry.date.isoformat().startswith(month)]
        recap = build_monthly_recap(month, entries)
        upsert_monthly_recap(self.diary_path, recap)
        return recap


def build_daily_entry(learning: LearningRepository, entry_date: date):
    activity_date = entry_date - timedelta(days=1)
    start = datetime.combine(activity_date, time.min)
    end = start + timedelta(days=1)
    examples = learning.learning_examples_between(start, end)
    attempts = learning.post_attempts_between(start, end)
    reviews = learning.reviews_between(start, end)
    snapshots = learning.engagement_snapshots_between(start, end)
    threshold_events = learning.system_events_between(start, end, "threshold_update")

    rewards = [example.reward_score for example in examples]
    average_reward = round(mean(rewards), 3) if rewards else 0.0
    attempts_posted = sum(1 for attempt in attempts if attempt.status == "posted")
    attempts_failed = sum(1 for attempt in attempts if attempt.status == "failed")
    reviews_approved = sum(1 for review in reviews if review.status == "approved")
    reviews_rejected = sum(1 for review in reviews if review.status == "rejected")
    removals = sum(1 for snapshot in snapshots if snapshot.is_removed)
    deletions = sum(1 for snapshot in snapshots if snapshot.is_deleted)
    negative_rewards = sum(1 for reward in rewards if reward < 0.25)

    metrics = {
        "learning_examples": len(examples),
        "post_attempts": len(attempts),
        "attempts_posted": attempts_posted,
        "attempts_failed": attempts_failed,
        "reviews_approved": reviews_approved,
        "reviews_rejected": reviews_rejected,
        "engagement_snapshots": len(snapshots),
        "removals": removals,
        "deletions": deletions,
        "negative_rewards": negative_rewards,
        "average_reward": average_reward,
        "threshold_updates": len(threshold_events),
    }
    return DiaryEntry(
        date=entry_date,
        yesterday=_build_yesterday(activity_date, metrics),
        what_happened=_build_what_happened(metrics),
        what_i_learned=_build_lesson(metrics),
        manual_notes=None,
        metrics=metrics,
    )


def build_monthly_recap(month: str, entries: list[DiaryEntry]):
    metrics = _sum_monthly_metrics(entries)
    if not entries:
        return MonthlyDiaryRecap(
            month=month,
            summary="No daily diary entries were available for this month.",
            lessons=["Keep collecting daily outcomes before changing strategy."],
            strategy_adjustments=["Do not adjust strategy from an empty memory window."],
            risk_notes=["No moderation or engagement signals were recorded in memory."],
        )
    average_reward = round(mean(float(entry.metrics.get("average_reward", 0.0)) for entry in entries), 3)
    summary = (
        f"{month} had {len(entries)} daily entries, {metrics['post_attempts']} post attempts, "
        f"{metrics['reviews_approved']} approvals, {metrics['reviews_rejected']} rejections, "
        f"and an average daily reward of {average_reward}."
    )
    lessons = _monthly_lessons(metrics, average_reward)
    return MonthlyDiaryRecap(
        month=month,
        summary=summary,
        lessons=lessons,
        strategy_adjustments=_monthly_strategy_adjustments(metrics, average_reward),
        risk_notes=_monthly_risk_notes(metrics),
    )


def _build_yesterday(activity_date: date, metrics: dict[str, int | float | str]):
    return (
        f"On {activity_date.isoformat()}, I observed {metrics['post_attempts']} post attempts, "
        f"{metrics['engagement_snapshots']} engagement snapshots, {metrics['learning_examples']} learning examples, "
        f"and {metrics['reviews_approved']} approved reviews."
    )


def _build_what_happened(metrics: dict[str, int | float | str]):
    if metrics["post_attempts"] == 0 and metrics["learning_examples"] == 0:
        return "There was no new posting or learning activity to summarize."
    parts = [
        f"{metrics['attempts_posted']} attempts were posted",
        f"{metrics['attempts_failed']} attempts failed",
        f"{metrics['reviews_approved']} reviews were approved",
        f"{metrics['reviews_rejected']} reviews were rejected",
    ]
    if metrics["removals"] or metrics["deletions"]:
        parts.append(f"{metrics['removals']} removals and {metrics['deletions']} deletions were observed")
    if metrics["threshold_updates"]:
        parts.append(f"{metrics['threshold_updates']} threshold updates were recorded")
    return "; ".join(parts) + "."


def _build_lesson(metrics: dict[str, int | float | str]):
    if metrics["removals"]:
        return "Recent moderation removals mean I should be more cautious and prefer review before promotional replies."
    if metrics["negative_rewards"]:
        return "Some replies produced weak reward signals, so I should use more specific, less promotional responses."
    if float(metrics["average_reward"]) >= 0.6:
        return "Recent outcomes were strong enough to keep using the current strategy while preserving policy constraints."
    if metrics["learning_examples"]:
        return "Recent outcomes were mixed, so I should avoid overconfident promotion and keep replies practical."
    return "No new outcome data arrived, so I should keep current behavior stable until more evidence appears."


def _sum_monthly_metrics(entries: list[DiaryEntry]):
    keys = [
        "post_attempts",
        "attempts_posted",
        "attempts_failed",
        "reviews_approved",
        "reviews_rejected",
        "engagement_snapshots",
        "removals",
        "deletions",
        "negative_rewards",
        "threshold_updates",
    ]
    return {key: sum(int(entry.metrics.get(key, 0)) for entry in entries) for key in keys}


def _monthly_lessons(metrics: dict[str, int], average_reward: float):
    lessons = []
    if average_reward >= 0.6:
        lessons.append("Helpful, specific replies appear to be working when the agent stays within policy constraints.")
    elif average_reward > 0:
        lessons.append("Outcomes were mixed, so the agent should prioritize specificity and lower promotional pressure.")
    else:
        lessons.append("There was not enough positive reward data to justify a more aggressive strategy.")
    if metrics["reviews_rejected"]:
        lessons.append("Rejected reviews should be treated as signal to make drafts more conservative before queueing.")
    return lessons


def _monthly_strategy_adjustments(metrics: dict[str, int], average_reward: float):
    if metrics["removals"] or metrics["deletions"]:
        return ["Prefer review routing and information-only replies until moderation signals calm down."]
    if average_reward >= 0.6 and metrics["attempts_posted"]:
        return ["Continue the current strategy mix, but keep memory guidance secondary to policy checks."]
    return ["Favor educational and comparative strategies over product mentions until stronger rewards accumulate."]


def _monthly_risk_notes(metrics: dict[str, int]):
    notes = []
    if metrics["removals"]:
        notes.append(f"{metrics['removals']} removals were recorded, so promotional routing should stay cautious.")
    if metrics["deletions"]:
        notes.append(f"{metrics['deletions']} deletions were recorded and should be reviewed before broadening posting.")
    if metrics["attempts_failed"]:
        notes.append(f"{metrics['attempts_failed']} posting failures occurred and may indicate transport or account friction.")
    if not notes:
        notes.append("No removals, deletions, or failed attempts were recorded in the monthly memory window.")
    return notes


def _recap_month_for(entry_date: date, force_monthly: bool):
    if force_monthly:
        return entry_date.strftime("%Y-%m")
    if entry_date.day == 1:
        return (entry_date - timedelta(days=1)).strftime("%Y-%m")
    return None
