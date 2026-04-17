from __future__ import annotations

from src.domain.models import DraftEvaluation, DraftReply, ThreadContext
from src.domain.policies import BANNED_HYPE_PHRASES, allowed_first_person, monetized_disclosure_required


class DraftEvaluator:
    def evaluate(self, thread: ThreadContext, draft: DraftReply):
        body_lower = draft.body.lower()
        authenticity = 0.9
        specificity = 0.7
        helpfulness = 0.78
        promo_pressure = 0.0
        policy = 1.0
        fail_reasons: list[str] = []

        if len(draft.body.split()) < 12:
            helpfulness -= 0.15
            fail_reasons.append("insufficient_value")
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

