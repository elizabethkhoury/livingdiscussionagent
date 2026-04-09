from pathlib import Path

from reddit_agent.rules import (
    detect_safety_block,
    load_lifecycle_rules,
    route_product,
    should_queue,
)


def test_route_product_prefers_prompthunt_for_prompt_storage():
    routed = route_product('Where do you store and reuse your best prompts?')
    assert routed == 'prompthunt.me'


def test_route_product_prefers_upwordly_for_linkedin_workflow():
    routed = route_product('How do founders turn expertise into LinkedIn posts consistently?')
    assert routed == 'upwordly.ai'


def test_detect_safety_block():
    assert (
        detect_safety_block('No self promotion or legal advice please')
        == 'hard_block:no self promo'
    )


def test_should_queue_against_thresholds():
    rules = load_lifecycle_rules(Path('config/rules'))
    assert should_queue(0.8, 0.2, 2.0, rules) is True
    assert should_queue(0.7, 0.2, 2.0, rules) is False
