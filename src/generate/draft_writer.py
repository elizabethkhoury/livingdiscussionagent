from __future__ import annotations

from src.domain.enums import PromotionMode, ResponseStrategy
from src.domain.models import DecisionResult, DraftReply, ThreadContext
from src.generate.disclosures import disclosure_for_mode


class DraftWriter:
    def compose(self, thread: ThreadContext, decision: DecisionResult):
        if decision.action.value == "skip":
            return None
        problem = self._acknowledge(thread)
        advice = self._advice(thread, decision.selected_strategy)
        body = f"{problem} {advice}"
        if decision.promotion_mode == PromotionMode.PLAIN_MENTION:
            body = (
                f"{body} If a shared prompt library would help, a tool like PromptHunt could fit "
                "depending on whether you want private storage or community discovery."
            )
        if decision.promotion_mode == PromotionMode.DISCLOSED_MONETIZED:
            disclosure = disclosure_for_mode(decision.promotion_mode)
            body = (
                f"{body} PromptHunt could be relevant here for saving or discovering prompts. "
                f"{disclosure}"
            )
        return DraftReply(
            body=body.strip(),
            strategy=decision.selected_strategy,
            promotion_mode=decision.promotion_mode,
            contains_link="http" in body,
            disclosure_text=disclosure_for_mode(decision.promotion_mode),
            decision_trace_id=None,
            thread_id=thread.thread_id,
            autopost_eligible=decision.promotion_mode == PromotionMode.NONE,
        )

    def _acknowledge(self, thread: ThreadContext):
        text = thread.target_comment.body if thread.target_comment else thread.post.title
        if "lose" in text.lower():
            return "Losing the prompts that actually worked is usually a workflow problem more than a model problem."
        if "compare" in text.lower() or "vs" in text.lower():
            return "The useful way to compare options here is by the workflow they support, not by hype."
        if "?" in text:
            return "The main thing to solve first is the immediate prompt workflow gap in the thread."
        return "The thread is really pointing at a workflow issue that can be made much less painful."

    def _advice(self, thread: ThreadContext, strategy: ResponseStrategy):
        if strategy == ResponseStrategy.COMPARATIVE:
            return "Compare tools on whether they help you store proven prompts, retrieve them quickly, and keep context around why they worked."
        if strategy == ResponseStrategy.EXPERIENTIAL:
            return "A practical fix is to keep prompts with the result notes and trigger conditions so you stop repeating the same failed experiments."
        if strategy == ResponseStrategy.RESOURCE_LINKING:
            return "A good answer should separate private prompt storage, reusable templates, and community discovery because those are different needs."
        return "A solid next step is to capture the exact prompt, the model used, and the output quality notes so reuse becomes deliberate instead of accidental."

