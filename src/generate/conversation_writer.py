"""Generates short, casual follow-up replies.

When a real Reddit user replies to one of our posted comments, this module
writes a low-key conversational response — *no product mentions*, no pitch,
no calls to action. The goal is "talking back like a normal commenter," not
"converting a lead."
"""

from __future__ import annotations

import logging
import re

from src.app.llm import HeuristicLLMClient, LLMClient, LLMMessage, get_llm_client
from src.domain.policies import BANNED_HYPE_PHRASES

logger = logging.getLogger(__name__)

MAX_FOLLOWUP_WORDS = 35
MAX_FOLLOWUP_SENTENCES = 2

# Hostility / toxicity heuristic — caught early so we don't spend an LLM call
# on obvious cases. The LLM judge handles the rest.
TOXIC_KEYWORDS = (
    "fuck off",
    "fuck you",
    "shut up",
    "kill yourself",
    "kys",
    "die in",
    "go die",
    "you're a bot",
    "youre a bot",
    "this is a bot",
    "spam",
    "spammer",
    "scam",
    "scammer",
    "report you",
    "reported",
    "downvoted",
    "trash post",
    "garbage",
    "stfu",
    "idiot",
    "moron",
    "retard",
)

LOW_VALUE_PATTERNS = (
    re.compile(r"^(thanks|thank you|ty|thx|cheers|cool|nice|ok|okay|yep|yes|no|lol|lmao|haha+|👍|🙏|✅|👌)[\s.!]*$", re.IGNORECASE),
    re.compile(r"^.{0,3}$"),  # Anything under 4 chars
)


def looks_low_value(reply_body: str) -> bool:
    text = (reply_body or "").strip()
    if not text:
        return True
    for pattern in LOW_VALUE_PATTERNS:
        if pattern.match(text):
            return True
    return False


def looks_toxic_heuristic(reply_body: str) -> bool:
    lower = (reply_body or "").lower()
    return any(keyword in lower for keyword in TOXIC_KEYWORDS)


class ConversationWriter:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or get_llm_client()

    def is_toxic(self, reply_body: str) -> bool:
        """Returns True if the reply is hostile, abusive, or accuses us of being a bot.

        Uses the heuristic blacklist first (free), then a tiny LLM check (cheap).
        Failsafe: if the LLM call errors, we treat the reply as toxic and skip
        — better to drop a borderline case than to engage a hostile one.
        """
        if looks_toxic_heuristic(reply_body):
            return True
        if isinstance(self.llm_client, HeuristicLLMClient):
            return False
        try:
            verdict = self.llm_client.complete(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "You judge whether a Reddit reply is hostile, insulting, or accusatory. "
                            "Reply ONLY with 'yes' or 'no'."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "Is this reply hostile, abusive, accusatory (calling someone a bot/scammer/spammer), "
                            "or otherwise something a calm person would not engage with? Reply 'yes' or 'no'.\n\n"
                            f"Reply text: {reply_body.strip()[:600]}"
                        ),
                    ),
                ]
            )
        except Exception as exc:
            logger.warning("Toxicity LLM check failed; treating as toxic. err=%s", exc)
            return True
        return verdict.strip().lower().startswith("y")

    def compose(
        self,
        *,
        original_post_title: str,
        our_previous_comment: str,
        reply_body: str,
        reply_author: str,
    ) -> str | None:
        """Produces a short conversational follow-up. Returns None if no good reply."""
        if looks_low_value(reply_body):
            return None
        if isinstance(self.llm_client, HeuristicLLMClient):
            return self._heuristic_reply(reply_body)
        prompt = self._build_prompt(
            original_post_title=original_post_title,
            our_previous_comment=our_previous_comment,
            reply_body=reply_body,
            reply_author=reply_author,
        )
        try:
            candidate = self.llm_client.complete(prompt)
        except Exception as exc:
            logger.warning("Conversation LLM failed; skipping reply. err=%s", exc)
            return None
        normalized = self._normalize(candidate)
        if not self._is_usable(normalized):
            return None
        return normalized

    def _build_prompt(self, *, original_post_title, our_previous_comment, reply_body, reply_author):
        instructions = "\n".join(
            [
                "You are continuing a Reddit conversation as the same author who posted the previous comment.",
                "Write a short, casual follow-up reply.",
                "",
                "Constraints:",
                "- 1-2 sentences. Hard cap: 35 words total.",
                "- Sound like a relaxed redditor, not a marketer or assistant.",
                "- No product mentions. No links. No 'check out' or 'you should try'.",
                "- No hype words like 'amazing', 'great', 'awesome', 'love'.",
                "- Don't restate what they said. Add one tiny new thought — a take, a small observation, a useful caveat, or a relevant tip.",
                "- Avoid ending with a question by default. Most follow-ups should end with your take or observation. Only ask a question maybe 1 in 4 times, and only if it's genuinely the most natural reply.",
                "- Don't apologize. Don't thank them excessively.",
                "- Lowercase casual is fine. Do not use bullet points or lists.",
                "- If their reply is just acknowledgment ('makes sense', 'fair'), don't reply at all — return the literal string SKIP.",
                "",
                "Context:",
                f"Original Reddit post title: {original_post_title}",
                f"Your previous comment in the thread: {our_previous_comment}",
                f"Their reply (by /u/{reply_author}): {reply_body}",
                "",
                "Output: just the reply text, no quotes, no preamble. Or the literal string SKIP if no good reply.",
            ]
        )
        return [
            LLMMessage(role="system", content="You write short, friendly Reddit follow-up replies."),
            LLMMessage(role="user", content=instructions),
        ]

    def _normalize(self, text: str) -> str:
        cleaned = " ".join((text or "").split()).strip()
        # Strip surrounding quotes if the model added them
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        return cleaned

    def _is_usable(self, text: str) -> bool:
        if not text:
            return False
        if text.upper() == "SKIP":
            return False
        words = text.split()
        if len(words) < 3 or len(words) > MAX_FOLLOWUP_WORDS:
            return False
        if self._sentence_count(text) > MAX_FOLLOWUP_SENTENCES:
            return False
        lower = text.lower()
        if "http" in lower or "www." in lower:
            return False
        if "prompthunt" in lower:
            return False
        if any(phrase in lower for phrase in BANNED_HYPE_PHRASES):
            return False
        if any(phrase in lower for phrase in ("check out", "you should try", "feel free to", "let me know if")):
            return False
        return True

    def _sentence_count(self, text: str) -> int:
        stripped = text.strip()
        if not stripped:
            return 0
        return len(re.findall(r"[.!?]+(?:\s|$)", stripped)) or 1

    def _heuristic_reply(self, reply_body: str) -> str | None:
        body_lower = (reply_body or "").lower()
        if "?" in reply_body:
            return "yeah depends on the setup honestly. what part are you trying to nail down first?"
        if any(word in body_lower for word in ("but", "however", "disagree", "actually")):
            return "fair point, that's the part i go back and forth on too."
        return None
