from __future__ import annotations

import logging
import re
import sys

from src.app.llm import HeuristicLLMClient, LLMClient, LLMMessage, get_llm_client
from src.app.settings import get_settings
from src.domain.enums import PromotionMode, ResponseStrategy
from src.domain.models import DecisionResult, DraftReply, MemoryContext, ThreadContext
from src.domain.policies import BANNED_HYPE_PHRASES
from src.generate.disclosures import disclosure_for_mode
from src.learn.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

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


class DraftWriter:
    def __init__(self, llm_client: LLMClient | None = None, memory_provider: MemoryProvider | None = None):
        self.llm_client = llm_client or get_llm_client()
        self.memory_provider = memory_provider or MemoryProvider()

    def compose(self, thread: ThreadContext, decision: DecisionResult):
        if decision.action.value == "skip":
            return None
        memory_context = self.memory_provider.get_context()
        body = self._generate_with_fallback(thread, decision, memory_context)
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

    def _generate_with_fallback(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext):
        generated_body = self._generate_body(thread, decision, memory_context)
        if generated_body:
            return generated_body
        return self._heuristic_body(thread, decision, memory_context)

    def _generate_body(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext):
        if isinstance(self.llm_client, HeuristicLLMClient):
            return None
        messages = self._build_prompt(thread, decision, memory_context)
        try:
            candidate = self.llm_client.complete(messages)
        except Exception as exc:
            settings = get_settings()
            message = "LLM generation timed out; using heuristic fallback" if type(exc).__name__ == "TimeoutError" else "LLM generation failed; using heuristic fallback"
            logger.warning(
                message,
                exc_info=sys.exc_info() if settings.openai_log_tracebacks else None,
                extra={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "llm_model": getattr(self.llm_client, "model", None),
                    "thread_id": thread.thread_id,
                    "subreddit": thread.post.subreddit,
                },
            )
            return None
        normalized_candidate = self._normalize_candidate(candidate, decision.promotion_mode)
        if self._is_usable_candidate(normalized_candidate, decision.promotion_mode, candidate):
            return normalized_candidate
        return None

    def _build_prompt(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext | None = None):
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
        memory_lines = []
        if memory_context and memory_context.prompt_text:
            memory_lines = [
                "",
                memory_context.prompt_text,
            ]
        user_prompt = "\n".join(
            [
                "Write a single Reddit reply for this thread.",
                f"Selected strategy: {strategy}.",
                f"Promotion mode: {decision.promotion_mode.value}.",
                disclosure_line,
                "Constraints:",
                "- Be helpful, specific, concise, and Reddit-native.",
                "- Write 2-4 sentences.",
                "- Use one compact paragraph.",
                "- Avoid long explanations, lists, and multi-paragraph replies.",
                "- Include one natural follow-up question when it would help continue the thread.",
                "- Do not force a question if it would sound awkward or bait-like.",
                "- Do not claim personal usage or experience.",
                "- Do not use hype language like best, amazing, must-have, or game changer.",
                "- Do not include links or URLs.",
                "- Do not sound salesy or aggressively promotional.",
                "- If promotion mode is none, do not mention PromptHunt.",
                "- Product mentions are optional unless promotion mode is disclosed_monetized.",
                "- If promotion mode is plain_mention, mention PromptHunt only if it directly improves the answer.",
                "- If promotion mode is disclosed_monetized, mention PromptHunt naturally and include the exact disclosure text.",
                "",
                "Thread context:",
                *thread_sections,
                *memory_lines,
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

    def _is_usable_candidate(self, candidate: str, promotion_mode: PromotionMode, raw_candidate: str | None = None):
        if not candidate or len(candidate.split()) < 12:
            return False
        if self._is_too_long(candidate):
            return False
        if raw_candidate and (self._has_paragraph_break(raw_candidate) or self._has_list_markers(raw_candidate)):
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
        if self._product_mention_required(promotion_mode) and "prompthunt" not in candidate_lower:
            return False
        return True

    def _heuristic_body(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext):
        sentences = [self._acknowledge(thread), self._advice(thread, decision.selected_strategy, memory_context)]
        caution = self._memory_caution(memory_context)
        if caution:
            sentences.append(caution)
        if self._should_mention_product(thread, decision):
            product_sentence = "PromptHunt could be relevant for saving or discovering prompts."
            disclosure = disclosure_for_mode(decision.promotion_mode)
            if disclosure:
                product_sentence = f"{product_sentence} {disclosure}"
            sentences.append(product_sentence)
        question = self._follow_up_question(thread)
        if question and decision.promotion_mode != PromotionMode.DISCLOSED_MONETIZED and len(sentences) < MAX_REPLY_SENTENCES:
            sentences.append(question)
        return " ".join(sentences).strip()

    def _acknowledge(self, thread: ThreadContext):
        text = thread.target_comment.body if thread.target_comment else thread.post.title
        if "lose" in text.lower():
            return "Losing the prompts that actually worked is usually a workflow problem more than a model problem."
        if "compare" in text.lower() or "vs" in text.lower():
            return "The useful way to compare options here is by the workflow they support, not by hype."
        if "?" in text:
            return "The main thing to solve first is the immediate prompt workflow gap in the thread."
        return "The thread is really pointing at a workflow issue that can be made much less painful."

    def _advice(self, thread: ThreadContext, strategy: ResponseStrategy, memory_context: MemoryContext):
        if self._memory_prefers_specificity(memory_context):
            return "Keep the reply anchored to the exact workflow details in the thread and avoid broad product claims."
        if strategy == ResponseStrategy.COMPARATIVE:
            return "Compare tools on whether they help you store proven prompts, retrieve them quickly, and keep context around why they worked."
        if strategy == ResponseStrategy.EXPERIENTIAL:
            return "A practical fix is to keep prompts with the result notes and trigger conditions so you stop repeating the same failed experiments."
        if strategy == ResponseStrategy.RESOURCE_LINKING:
            return "A good answer should separate private prompt storage, reusable templates, and community discovery because those are different needs."
        return "A solid next step is to capture the exact prompt, the model used, and the output quality notes so reuse becomes deliberate instead of accidental."

    def _memory_prefers_specificity(self, memory_context: MemoryContext):
        memory_text = memory_context.prompt_text.lower()
        return "more specific" in memory_text or "prioritize specificity" in memory_text

    def _memory_caution(self, memory_context: MemoryContext):
        removals = sum(int(entry.metrics.get("removals", 0)) for entry in memory_context.daily_entries)
        negative_rewards = sum(int(entry.metrics.get("negative_rewards", 0)) for entry in memory_context.daily_entries)
        if removals or negative_rewards:
            return "Given recent outcome signals, keep the tone practical and avoid pushing a tool unless it directly fits the request."
        return ""

    def _sentence_count(self, text: str):
        stripped = text.strip()
        if not stripped:
            return 0
        count = len(re.findall(r"[.!?]+(?:\s|$)", stripped))
        return count or 1

    def _has_follow_up_question(self, text: str):
        return "?" in text

    def _is_too_long(self, text: str):
        if len(text.split()) > MAX_REPLY_WORDS:
            return True
        if self._sentence_count(text) > MAX_REPLY_SENTENCES:
            return True
        if self._has_paragraph_break(text):
            return True
        return self._has_list_markers(text)

    def _product_mention_required(self, promotion_mode: PromotionMode):
        return promotion_mode == PromotionMode.DISCLOSED_MONETIZED

    def _should_mention_product(self, thread: ThreadContext, decision: DecisionResult):
        if decision.promotion_mode == PromotionMode.DISCLOSED_MONETIZED:
            return True
        if decision.promotion_mode == PromotionMode.NONE:
            return False
        text = thread.combined_text.lower()
        return any(term in text for term in PRODUCT_FIT_TERMS)

    def _follow_up_question(self, thread: ThreadContext):
        text = thread.combined_text.lower()
        if "compare" in text or " vs " in text:
            return "Are you comparing personal storage, team sharing, or public discovery?"
        if "discover" in text or "shared" in text or "community" in text:
            return "Are you mainly looking for private storage or community discovery?"
        if "lose" in text or "save prompts" in text or "reuse" in text or "workflow" in text:
            return "Are you mainly losing prompts across tools, or forgetting which version produced the good output?"
        if "?" in thread.combined_text:
            return "What part of the workflow is breaking most often?"
        return ""

    def _has_paragraph_break(self, text: str):
        return bool(re.search(r"\n\s*\n", text.strip()))

    def _has_list_markers(self, text: str):
        return bool(re.search(r"(^|\n)\s*(?:[-*]|\d+[.)])\s+", text))
