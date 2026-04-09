from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reddit_agent.seeds import ANTI_PROMOTION_KEYWORDS, PROMPTHUNT_KEYWORDS, UPWORDLY_KEYWORDS


@dataclass(slots=True)
class SubredditRule:
    name: str
    allow_promotion: bool
    allow_links: bool
    tags: list[str]
    notes: str


@dataclass(slots=True)
class ProductRule:
    name: str
    summary: str
    keywords: list[str]
    blocked_phrases: list[str]


@dataclass(slots=True)
class LifecycleRules:
    stressed_below: float
    retire_below: float
    reset_score: float
    strict_mode_days: int
    model_confidence_min: float
    risk_score_max: float
    expected_value_min: float


def _load_yaml(path: Path):
    with path.open('r', encoding='utf-8') as handle:
        return yaml.safe_load(handle)


def load_subreddit_rules(config_dir: Path):
    payload = _load_yaml(config_dir / 'subreddit_profiles.yaml')
    return {
        item['name'].lower(): SubredditRule(
            name=item['name'],
            allow_promotion=item['allow_promotion'],
            allow_links=item['allow_links'],
            tags=item['tags'],
            notes=item['notes'],
        )
        for item in payload['subreddits']
    }


def load_product_rules(config_dir: Path):
    payload = _load_yaml(config_dir / 'products.yaml')
    return {
        name: ProductRule(
            name=name,
            summary=details['summary'],
            keywords=details['keywords'],
            blocked_phrases=details['blocked_phrases'],
        )
        for name, details in payload['products'].items()
    }


def load_lifecycle_rules(config_dir: Path):
    payload = _load_yaml(config_dir / 'lifecycle.yaml')
    return LifecycleRules(
        stressed_below=payload['reward_thresholds']['stressed_below'],
        retire_below=payload['reward_thresholds']['retire_below'],
        reset_score=payload['reward_thresholds']['reset_score'],
        strict_mode_days=payload['reward_thresholds']['strict_mode_days'],
        model_confidence_min=payload['queue_thresholds']['model_confidence_min'],
        risk_score_max=payload['queue_thresholds']['risk_score_max'],
        expected_value_min=payload['queue_thresholds']['expected_value_min'],
    )


def detect_safety_block(text: str):
    lowered = text.lower()
    for phrase in ANTI_PROMOTION_KEYWORDS:
        if phrase in lowered:
            return f'hard_block:{phrase}'
    return None


def route_product(text: str):
    lowered = text.lower()
    prompt_hits = sum(1 for phrase in PROMPTHUNT_KEYWORDS if phrase in lowered)
    linkedin_hits = sum(1 for phrase in UPWORDLY_KEYWORDS if phrase in lowered)
    if prompt_hits == 0 and linkedin_hits == 0:
        return None
    if prompt_hits >= linkedin_hits:
        return 'prompthunt.me'
    return 'upwordly.ai'


def should_queue(
    model_confidence: float, risk_score: float, expected_value: float, rules: LifecycleRules
):
    return (
        model_confidence >= rules.model_confidence_min
        and risk_score <= rules.risk_score_max
        and expected_value >= rules.expected_value_min
    )
