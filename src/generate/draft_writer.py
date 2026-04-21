from __future__ import annotations

from src.app.llm import HeuristicLLMClient, LLMClient, LLMMessage, get_llm_client
from src.domain.enums import PromotionMode, ResponseStrategy
from src.domain.models import DecisionResult, DraftReply, ThreadContext
from src.domain.policies import BANNED_HYPE_PHRASES
from src.generate.disclosures import disclosure_for_mode


class DraftWriter:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or get_llm_client()

    def compose(self, thread: ThreadContext, decision: DecisionResult):
        if decision.action.value == "skip":
            return None
        body = self._generate_with_fallback(thread, decision)
        disclosure = disclosure_for_mode(decision.promotion_mode)
        if decision.promotion_mode == PromotionMode.DISCLOSED_MONETIZED and disclosure and disclosure not in body:
            body = f"{body} {disclosure}".strip()
        return DraftReply(
            body=body.strip(),
            strategy=decision.selected_strategy,
            promotion_mode=decision.promotion_mode,
            contains_link="http" in body,
            disclosure_text=disclosure,
            decision_trace_id=None,
            thread_id=thread.thread_id,
            autopost_eligible=decision.promotion_mode == PromotionMode.NONE,
        )

    def _generate_with_fallback(self, thread: ThreadContext, decision: DecisionResult):
        generated_body = self._generate_body(thread, decision)
        if generated_body:
            return generated_body
        return self._heuristic_body(thread, decision)

    def _generate_body(self, thread: ThreadContext, decision: DecisionResult):
        if isinstance(self.llm_client, HeuristicLLMClient):
            return None
        messages = self._build_prompt(thread, decision)
        try:
            candidate = self.llm_client.complete(messages)
        except Exception:
            return None
        normalized_candidate = self._normalize_candidate(candidate, decision.promotion_mode)
        if self._is_usable_candidate(normalized_candidate, decision.promotion_mode):
            return normalized_candidate
        return None

    def _build_prompt(self, thread: ThreadContext, decision: DecisionResult):
        disclosure = disclosure_for_mode(decision.promotion_mode)
        strategy = decision.selected_strategy.value.replace("_", " ")
        thread_sections = [
            f"Subreddit: {thread.post.subreddit}",
            f"Post title: {thread.post.title}",
        ]
        if thread.post.body:
            thread_sections.append(f"Post body: {thread.post.body}")
        if thread.target_comment:
            thread_sections.append(f"Target comment: {thread.target_comment.body}")
        if disclosure:
            disclosure_line = f"Required disclosure text: {disclosure}"
        else:
            disclosure_line = "Required disclosure text: none"
        user_prompt = "\n".join(
            [
                "Write a single Reddit reply for this thread.",
                f"Selected strategy: {strategy}.",
                f"Promotion mode: {decision.promotion_mode.value}.",
                disclosure_line,
                "Constraints:",
                "- Be helpful, specific, concise, and Reddit-native.",
                "- Do not claim personal usage or experience.",
                "- Do not use hype language like best, amazing, must-have, or game changer.",
                "- Do not include links or URLs.",
                "- Do not sound salesy or aggressively promotional.",
                "- If promotion mode is none, do not mention PromptHunt.",
                "- If promotion mode is plain_mention, a soft PromptHunt mention is allowed but not required.",
                "- If promotion mode is disclosed_monetized, mention PromptHunt naturally and include the exact disclosure text.",
                "",
                "Thread context:",
                *thread_sections,
                "",
                "Return only the reply body as plain text.",
            ]
        )
        return [
            LLMMessage(
                role="system",
                content="You write policy-safe Reddit replies that are useful first and promotional only when explicitly allowed.",
            ),
            LLMMessage(role="user", content=user_prompt),
        ]

    def _normalize_candidate(self, candidate: str, promotion_mode: PromotionMode):
        normalized = " ".join(candidate.split()).strip()
        if promotion_mode == PromotionMode.DISCLOSED_MONETIZED:
            disclosure = disclosure_for_mode(promotion_mode)
            if disclosure and disclosure not in normalized:
                normalized = f"{normalized} {disclosure}".strip()
        return normalized

    def _is_usable_candidate(self, candidate: str, promotion_mode: PromotionMode):
        if not candidate or len(candidate.split()) < 12:
            return False
        candidate_lower = candidate.lower()
        if "http" in candidate_lower or "www." in candidate_lower:
            return False
        if "i use" in candidate_lower or "someone mentioned" in candidate_lower:
            return False
        if any(phrase in candidate_lower for phrase in BANNED_HYPE_PHRASES):
            return False
        if promotion_mode == PromotionMode.NONE and "prompthunt" in candidate_lower:
            return False
        return True

    def _heuristic_body(self, thread: ThreadContext, decision: DecisionResult):
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
        return body.strip()

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
