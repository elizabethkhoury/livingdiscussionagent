from datetime import date

from src.domain.models import DiaryEntry, MonthlyDiaryRecap
from src.learn.diary_memory import ensure_diary_file, load_memory_context, upsert_daily_entry, upsert_monthly_recap


def make_entry(day: date, lesson: str):
    return DiaryEntry(
        date=day,
        yesterday=f"Yesterday summary for {day.isoformat()}",
        what_happened="A useful event happened.",
        what_i_learned=lesson,
        metrics={"post_attempts": 1, "average_reward": 0.5},
    )


def test_ensure_diary_file_creates_markdown(tmp_path):
    path = tmp_path / "memory" / "agent_diary.md"

    ensure_diary_file(path)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "# Agent Diary Memory" in text
    assert "## Daily Entries" in text
    assert "## Monthly Recaps" in text


def test_load_memory_context_limits_latest_entries_and_recaps(tmp_path):
    path = tmp_path / "agent_diary.md"
    upsert_daily_entry(path, make_entry(date(2026, 4, 27), "Older lesson."))
    upsert_daily_entry(path, make_entry(date(2026, 4, 28), "Middle lesson."))
    upsert_daily_entry(path, make_entry(date(2026, 4, 29), "Latest lesson."))
    upsert_monthly_recap(path, MonthlyDiaryRecap(month="2026-02", summary="Old month.", lessons=["old"]))
    upsert_monthly_recap(path, MonthlyDiaryRecap(month="2026-03", summary="Middle month.", lessons=["middle"]))
    upsert_monthly_recap(path, MonthlyDiaryRecap(month="2026-04", summary="Latest month.", lessons=["latest"]))

    context = load_memory_context(path, recent_days=2, recap_months=1)

    assert [entry.date for entry in context.daily_entries] == [date(2026, 4, 29), date(2026, 4, 28)]
    assert [recap.month for recap in context.monthly_recaps] == ["2026-04"]
    assert "Latest lesson." in context.prompt_text
    assert "Latest month." in context.prompt_text


def test_upsert_daily_entry_preserves_manual_notes_and_avoids_duplicates(tmp_path):
    path = tmp_path / "agent_diary.md"
    day = date(2026, 4, 29)
    upsert_daily_entry(
        path,
        make_entry(day, "Initial lesson.").model_copy(update={"manual_notes": "Operator note to keep."}),
    )

    upsert_daily_entry(path, make_entry(day, "Updated lesson."))

    text = path.read_text(encoding="utf-8")
    context = load_memory_context(path, recent_days=30, recap_months=6)
    assert text.count("### 2026-04-29") == 1
    assert context.daily_entries[0].what_i_learned == "Updated lesson."
    assert context.daily_entries[0].manual_notes == "Operator note to keep."
