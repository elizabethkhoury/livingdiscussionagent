from __future__ import annotations

import re

from src.domain.enums import PromotionMode
from src.domain.models import DraftEvaluation, DraftReply, ThreadContext
from src.domain.policies import BANNED_HYPE_PHRASES, allowed_first_person, monetized_disclosure_required

MAX_REPLY_WORDS = 85
MAX_REPLY_SENTENCES = 4
PRODUCT_FIT_TERMS = [
    "save prompts",
    "organize prompts",
    "find prompts",
    "reuse prompts",
    "prompt library",
    "prompt libraries",
    "prompt repository",
    "shared prompts",
    "prompt management",
    "workflow",
]


class DraftEvaluator:
    def evaluate(self, thread: ThreadContext, draft: DraftReply):
        body_lower = draft.body.lower()
        authenticity = 0.9
        specificity = 0.7
        helpfulness = 0.78
        promo_pressure = 0.0
        policy = 1.0
        fail_reasons: list[str] = []
        word_count = len(draft.body.split())
        sentence_count = _sentence_count(draft.body)

        if word_count < 12:
            helpfulness -= 0.15
            fail_reasons.append("insufficient_value")
        if word_count > MAX_REPLY_WORDS:
            helpfulness -= 0.10
            fail_reasons.append("too_long")
        if sentence_count > MAX_REPLY_SENTENCES:
            helpfulness -= 0.10
            fail_reasons.append("too_many_sentences")
        if _has_paragraph_break(draft.body):
            helpfulness -= 0.08
            fail_reasons.append("paragraph_heavy")
        if any(phrase in body_lower for phrase in BANNED_HYPE_PHRASES):
            promo_pressure += 0.35
            policy -= 0.2
            fail_reasons.append("hype_language")
        if "i use" in body_lower and not allowed_first_person():
            authenticity -= 0.35
            policy -= 0.3
            fail_reasons.append("deception")
        if "someone mentioned" in body_lower:
            authenticity -= 0.35
            policy -= 0.2
            fail_reasons.append("deception")
        if "prompt" in thread.combined_text.lower():
            specificity += 0.12
        if "prompthunt" in body_lower:
            promo_pressure += 0.15
        if draft.promotion_mode == PromotionMode.PLAIN_MENTION and "prompthunt" in body_lower and not _has_product_fit(thread):
            promo_pressure += 0.20
            fail_reasons.append("unnecessary_product_mention")
        if "?" in draft.body:
            helpfulness += 0.04
        if monetized_disclosure_required(draft.body) and not draft.disclosure_text:
            policy -= 0.5
            fail_reasons.append("undisclosed_monetization")
        overall = max(0.0, min((authenticity + specificity + helpfulness + policy - promo_pressure) / 4, 1.0))
        return DraftEvaluation(
            authenticity_score=max(0.0, min(authenticity, 1.0)),
            specificity_score=max(0.0, min(specificity, 1.0)),
            helpfulness_score=max(0.0, min(helpfulness, 1.0)),
            promo_pressure_score=max(0.0, min(promo_pressure, 1.0)),
            policy_compliance_score=max(0.0, min(policy, 1.0)),
            overall_score=overall,
            fail_reasons=fail_reasons,
        )


def _sentence_count(text: str):
    stripped = text.strip()
    if not stripped:
        return 0
    count = len(re.findall(r"[.!?]+(?:\s|$)", stripped))
    return count or 1


def _has_paragraph_break(text: str):
    return bool(re.search(r"\n\s*\n", text.strip()))


def _has_product_fit(thread: ThreadContext):
    text = thread.combined_text.lower()
    return any(term in text for term in PRODUCT_FIT_TERMS)
