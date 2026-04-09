from pathlib import Path

from reddit_agent.models import HealthState
from reddit_agent.rules import load_lifecycle_rules
from reddit_agent.services.health import determine_health_state


def test_health_enters_mature_after_approved_actions():
    rules = load_lifecycle_rules(Path('config/rules'))
    state = determine_health_state(
        score=60,
        approved_actions=25,
        paused_days=0,
        negative_reflections=0,
        rules=rules,
    )
    assert state == HealthState.mature


def test_health_retires_when_negative_reflections_stack():
    rules = load_lifecycle_rules(Path('config/rules'))
    state = determine_health_state(
        score=-1,
        approved_actions=10,
        paused_days=0,
        negative_reflections=3,
        rules=rules,
    )
    assert state == HealthState.retired
