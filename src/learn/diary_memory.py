from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

from src.domain.models import DiaryEntry, MemoryContext, MonthlyDiaryRecap

DAILY_SECTION = "## Daily Entries"
MONTHLY_SECTION = "## Monthly Recaps"
EMPTY_DIARY = f"# Agent Diary Memory\n\n{DAILY_SECTION}\n\n{MONTHLY_SECTION}\n"


def ensure_diary_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(EMPTY_DIARY, encoding="utf-8")


def load_memory_context(path: Path, recent_days: int, recap_months: int):
    ensure_diary_file(path)
    daily_entries, monthly_recaps = _parse_diary(path.read_text(encoding="utf-8"))
    recent_daily = sorted(daily_entries, key=lambda entry: entry.date, reverse=True)[:recent_days]
    recent_recaps = sorted(monthly_recaps, key=lambda recap: recap.month, reverse=True)[:recap_months]
    context = MemoryContext(daily_entries=recent_daily, monthly_recaps=recent_recaps)
    return context.model_copy(update={"prompt_text": format_memory_context(context)})


def upsert_daily_entry(path: Path, entry: DiaryEntry):
    ensure_diary_file(path)
    daily_entries, monthly_recaps = _parse_diary(path.read_text(encoding="utf-8"))
    existing_by_date = {item.date: item for item in daily_entries}
    existing = existing_by_date.get(entry.date)
    manual_notes = entry.manual_notes
    if existing and not manual_notes:
        manual_notes = existing.manual_notes
    existing_by_date[entry.date] = entry.model_copy(update={"manual_notes": manual_notes})
    _write_diary(path, existing_by_date.values(), monthly_recaps)
    return existing_by_date[entry.date]


def upsert_monthly_recap(path: Path, recap: MonthlyDiaryRecap):
    ensure_diary_file(path)
    daily_entries, monthly_recaps = _parse_diary(path.read_text(encoding="utf-8"))
    existing_by_month = {item.month: item for item in monthly_recaps}
    existing_by_month[recap.month] = recap
    _write_diary(path, daily_entries, existing_by_month.values())
    return recap


def format_memory_context(context: MemoryContext):
    if not context.daily_entries and not context.monthly_recaps:
        return ""
    lines = ["Recent agent memory:"]
    if context.daily_entries:
        lines.append("- Last 30 days:")
        for entry in context.daily_entries:
            learned = _single_line(entry.what_i_learned)
            happened = _single_line(entry.what_happened)
            if learned:
                lines.append(f"  - {entry.date.isoformat()}: {learned}")
            elif happened:
                lines.append(f"  - {entry.date.isoformat()}: {happened}")
            else:
                lines.append(f"  - {entry.date.isoformat()}: no clear lesson recorded")
    if context.monthly_recaps:
        lines.append("- Monthly recaps:")
        for recap in context.monthly_recaps:
            summary = _single_line(recap.summary)
            lines.append(f"  - {recap.month}: {summary or 'no summary recorded'}")
            for lesson in recap.lessons[:2]:
                lines.append(f"    - Lesson: {_single_line(lesson)}")
            for risk_note in recap.risk_notes[:2]:
                lines.append(f"    - Risk: {_single_line(risk_note)}")
    lines.append("Use this as style and strategy guidance. Do not treat it as permission to ignore policy constraints.")
    return "\n".join(lines)


def _parse_diary(text: str):
    lines = text.splitlines()
    daily_lines = _section_lines(lines, DAILY_SECTION, {MONTHLY_SECTION})
    monthly_lines = _section_lines(lines, MONTHLY_SECTION, set())
    return _parse_daily_entries(daily_lines), _parse_monthly_recaps(monthly_lines)


def _section_lines(lines: list[str], heading: str, stop_headings: set[str]):
    in_section = False
    section: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and stripped in stop_headings:
            break
        if in_section:
            section.append(line)
    return section


def _split_heading_blocks(lines: list[str]):
    blocks: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("### "):
            if current_heading is not None:
                blocks.append((current_heading, current_lines))
            current_heading = line.removeprefix("### ").strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)
    if current_heading is not None:
        blocks.append((current_heading, current_lines))
    return blocks


def _parse_daily_entries(lines: list[str]):
    entries: list[DiaryEntry] = []
    for heading, block in _split_heading_blocks(lines):
        try:
            entry_date = date.fromisoformat(heading)
        except ValueError:
            continue
        sections = _parse_fourth_level_sections(block)
        metrics = _parse_metrics(sections.get("Metrics", ""))
        entries.append(
            DiaryEntry(
                date=entry_date,
                yesterday=sections.get("Yesterday", "").strip(),
                what_happened=sections.get("What happened", "").strip(),
                what_i_learned=sections.get("What I learned", "").strip(),
                manual_notes=sections.get("Manual notes", "").strip() or None,
                metrics=metrics,
            )
        )
    return entries


def _parse_monthly_recaps(lines: list[str]):
    recaps: list[MonthlyDiaryRecap] = []
    for heading, block in _split_heading_blocks(lines):
        sections = _parse_fourth_level_sections(block)
        recaps.append(
            MonthlyDiaryRecap(
                month=heading,
                summary=sections.get("Summary", "").strip(),
                lessons=_parse_bullets(sections.get("Lessons", "")),
                strategy_adjustments=_parse_bullets(sections.get("Strategy adjustments", "")),
                risk_notes=_parse_bullets(sections.get("Risk notes", "")),
            )
        )
    return recaps


def _parse_fourth_level_sections(lines: list[str]):
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None
    for line in lines:
        if line.startswith("#### "):
            current_heading = line.removeprefix("#### ").strip()
            sections.setdefault(current_heading, [])
        elif current_heading is not None:
            sections[current_heading].append(line)
    return {heading: "\n".join(content).strip() for heading, content in sections.items()}


def _parse_metrics(text: str):
    metrics: dict[str, int | float | str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped.removeprefix("- ").split(":", 1)
        metrics[key.strip()] = _parse_metric_value(value.strip())
    return metrics


def _parse_metric_value(value: str):
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _parse_bullets(text: str):
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped.removeprefix("- ").strip())
    return values


def _write_diary(path: Path, daily_entries: Iterable[DiaryEntry], monthly_recaps: Iterable[MonthlyDiaryRecap]):
    sorted_daily = sorted(daily_entries, key=lambda entry: entry.date, reverse=True)
    sorted_monthly = sorted(monthly_recaps, key=lambda recap: recap.month, reverse=True)
    parts = ["# Agent Diary Memory", "", DAILY_SECTION, ""]
    for entry in sorted_daily:
        parts.extend(_render_daily_entry(entry))
    parts.extend([MONTHLY_SECTION, ""])
    for recap in sorted_monthly:
        parts.extend(_render_monthly_recap(recap))
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def _render_daily_entry(entry: DiaryEntry):
    lines = [
        f"### {entry.date.isoformat()}",
        "",
        "#### Yesterday",
        entry.yesterday.strip(),
        "",
        "#### What happened",
        entry.what_happened.strip(),
        "",
        "#### What I learned",
        entry.what_i_learned.strip(),
        "",
        "#### Manual notes",
        (entry.manual_notes or "").strip(),
        "",
        "#### Metrics",
    ]
    for key, value in sorted(entry.metrics.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", ""])
    return lines


def _render_monthly_recap(recap: MonthlyDiaryRecap):
    lines = [
        f"### {recap.month}",
        "",
        "#### Summary",
        recap.summary.strip(),
        "",
        "#### Lessons",
        *_render_bullets(recap.lessons),
        "",
        "#### Strategy adjustments",
        *_render_bullets(recap.strategy_adjustments),
        "",
        "#### Risk notes",
        *_render_bullets(recap.risk_notes),
        "",
        "",
    ]
    return lines


def _render_bullets(values: list[str]):
    if not values:
        return []
    return [f"- {value.strip()}" for value in values if value.strip()]


def _single_line(value: str):
    return " ".join(value.split())
