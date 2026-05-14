"""Test-wide isolation from production state.

The `memory/agent_diary.md` file is mutated by the running loop. When tests
import the decision engine or draft writer, they instantiate a real
MemoryProvider which reads that file. If the live diary contains negative
reward signals or "more specific" guidance, decision/draft logic switches
to cautious branches and breaks tests that don't account for memory state.

This conftest points MEMORY_DIARY_PATH at a temp file for the whole test
session so the live diary can't influence tests.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_memory_diary():
    tmp_dir = tempfile.mkdtemp(prefix="livingdiscussionagent_test_memory_")
    diary_path = os.path.join(tmp_dir, "agent_diary.md")
    with open(diary_path, "w") as f:
        f.write("# Agent Diary Memory\n\n## Daily Entries\n\n## Monthly Recaps\n")
    prev = os.environ.get("MEMORY_DIARY_PATH")
    os.environ["MEMORY_DIARY_PATH"] = diary_path
    # Clear the settings cache so tests see the new env value.
    try:
        from src.app.settings import get_settings
        get_settings.cache_clear()
    except Exception:
        pass
    yield
    if prev is None:
        os.environ.pop("MEMORY_DIARY_PATH", None)
    else:
        os.environ["MEMORY_DIARY_PATH"] = prev
