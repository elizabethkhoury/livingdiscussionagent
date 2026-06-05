from __future__ import annotations

import hashlib
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
from src.learn.voice_sampler import VoiceSampler

logger = logging.getLogger(__name__)

MAX_REPLY_WORDS = 45
MAX_REPLY_SENTENCES = 4
MIN_REPLY_WORDS = 8
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
    def __init__(self, llm_client: LLMClient | None = None, memory_provider: MemoryProvider | None = None, voice_sampler: VoiceSampler | None = None):
        self.llm_client = llm_client or get_llm_client()
        self.memory_provider = memory_provider or MemoryProvider()
        self.voice_sampler = voice_sampler or VoiceSampler()

    def compose(self, thread: ThreadContext, decision: DecisionResult):
        if decision.action.value == "skip":
            return None
        memory_context = self.memory_provider.get_context()
        body = self._generate_with_fallback(thread, decision, memory_context)
        # Final gate: does the reply actually address what the OP is talking about?
        # This catches the "off-topic non-sequitur" failure mode where the bot pastes
        # a prompt-storage template into a thread that has nothing to do with prompts.
        if not self._is_on_topic(thread, body):
            logger.warning(
                "draft rejected as off-topic for thread",
                extra={"thread_id": thread.thread_id, "subreddit": thread.post.subreddit, "body_preview": body[:120]},
            )
            return None
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
            # Drafts that only mention PromptHunt in passing (plain_mention) are also
            # autopost-eligible, but the review_worker applies a separate `max_promo_posts_per_day`
            # cap so they stay rare. DISCLOSED_MONETIZED (with explicit affiliate disclosure) still
            # requires human review because it has stronger compliance implications.
            autopost_eligible=decision.promotion_mode in (PromotionMode.NONE, PromotionMode.PLAIN_MENTION),
        )

    def _generate_with_fallback(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext):
        generated_body = self._generate_body(thread, decision, memory_context)
        if generated_body:
            return generated_body
        raw = self._heuristic_body(thread, decision, memory_context)
        return self._strip_ai_tells(raw)

    def _is_on_topic(self, thread: ThreadContext, body: str) -> bool:
        """Reject drafts that don't actually address the OP's topic.

        Catches the failure mode where the bot pastes a stock prompt-storage
        reply into threads about, e.g., LLM optimization, AI clickbait tone,
        or unrelated dev topics. We ask the LLM a single yes/no question.
        Fail-closed: if the judge call errors, we keep the draft (the regular
        quality gates downstream will still filter obvious junk).
        """
        if isinstance(self.llm_client, HeuristicLLMClient):
            return True
        op_text = (thread.post.title or "") + "\n" + (thread.post.body or "")
        if thread.target_comment:
            op_text += "\n\nTarget comment to reply to: " + (thread.target_comment.body or "")
        prompt = [
            LLMMessage(
                role="system",
                content=(
                    "You are a strict moderator deciding whether a Reddit reply makes sense as a "
                    "direct response to a post. Answer ONLY 'yes' or 'no'."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    "Reddit post (and possibly a target comment):\n"
                    f"{op_text[:2000]}\n\n"
                    "Proposed reply:\n"
                    f"{body[:1000]}\n\n"
                    "Question: Does the proposed reply directly address the actual topic the post "
                    "or target comment is about? If the reply is a non-sequitur, generic template, "
                    "or talks about something unrelated, answer 'no'. If it genuinely engages with "
                    "the OP's actual topic, answer 'yes'. Reply with one word only."
                ),
            ),
        ]
        try:
            verdict = self.llm_client.complete(prompt)
        except Exception:
            return True  # Don't block on judge errors; downstream gates still apply.
        v = verdict.strip().lower()
        # Only reject when the judge explicitly says "no". Any other response
        # (yes, ambiguous, or a stub returning unrelated text) is treated as pass.
        # This keeps the gate strict-on-no but tolerant of LLM noise.
        return not v.startswith("no")

    def _generate_body(self, thread: ThreadContext, decision: DecisionResult, memory_context: MemoryContext):
        if isinstance(self.llm_client, HeuristicLLMClient):
            return None
        messages = self._build_prompt(thread, decision, memory_context)
        # Retry up to 3 times. The LLM is non-deterministic and ~40% of single-shot outputs
        # fail _is_usable_candidate (too long, hype phrases, etc.). With ~60% per-call
        # pass rate, 3 tries reach ~94% effective success, which keeps us off the
        # hardcoded heuristic fallback that produces identical sentences.
        for attempt in range(3):
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
                        "attempt": attempt + 1,
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
                "- Be helpful, specific, casual, and Reddit-native.",
                "- Aim for 20-40 words. Hard cap: 45 words. Minimum: 8 words.",
                "- One compact comment. No lists, no multi-paragraph replies.",
                "- Reply directly to what the OP or target comment is actually asking. Add real signal, not commentary.",
                "- It's OK to drop articles ('works fine on m1'), drop periods at the end, write fragments, or comma-splice. Don't force formal transitions between sentences. Reddit comments often have no transitions at all.",
                "- Lowercase casual is fine. Light typos / contractions ('tho', 'kinda', 'tbh', 'fwiw', 'ngl', 'idk', 'imo', 'ymmv') are fine in moderation. Don't pile them on.",
                "- VARY your phrasing across replies. Do not reuse stock phrases like 'a solid next step', 'workflow gap', 'capture the exact prompt', 'deliberate instead of accidental', 'workflow they support'. Find a fresh way to say what you mean.",
                "- Avoid stock openers like 'Great point', 'Interesting take', 'This is a common challenge'. Start with the actual idea.",
                "- Sound like a different redditor than the last comment you'd write. Different sentence structure, different word choices.",
                "",
                "",
                *self._voice_examples_lines(thread.post.subreddit),
                "",
                "CONCRETE > ABSTRACT (most important rule — abstract essay-style replies get flagged as bot):",
                "- Anchor your reply to ONE specific detail from the OP. Mention a tool, a number, a tradeoff, a step, a phrase they used — something a generic reply couldn't.",
                "- BAD (could apply to any thread): 'transitioning from a demo to production reveals critical gaps. The foundation matters as much as the polish.'",
                "- GOOD (anchored): 'the demo-to-prod gap usually hits hardest on auth and rate limiting. those don't show up until you have real users'",
                "- Skip generic wisdom about software/workflows/AI. If your reply would make sense pasted under any other post in the subreddit, rewrite it.",
                "- Do not write abstract observations about 'the reality of', 'beneath the surface', 'in real-world use'. Real redditors are concrete.",
                "",
                "HUMAN VOICE — STRICT RULES (these are the patterns that get called out as bot in the wild):",
                "- NEVER use em dashes (—) or en dashes (–). Use commas, periods, or rephrase.",
                "- NEVER use semicolons. Real Reddit comments almost never have semicolons; they read as essay/AI.",
                "- NEVER use smart quotes ('' or \"\"). Plain ASCII only.",
                "- NEVER use exclamation marks.",
                "- NEVER start with: 'It sounds like', 'It's great to see', 'It's exciting', 'It's crucial', 'It's fascinating', 'Such details', 'Keep up', 'I appreciate', 'Indeed,', 'Ultimately,', 'In summary', 'Absolutely,', 'Certainly,', 'Of course,'.",
                "- NEVER use these words or phrases (they are the most common AI tells — using even one flags the comment as a bot):",
                "  leverage, utilize, streamline, holistic, synergy, pivotal, paramount, empower, foster, resonate,",
                "  transformative, groundbreaking, revolutionary, cutting-edge, innovative, ecosystem, scalable,",
                "  robust, nuanced, proactive, elevate, facilitate, undeniably, noteworthy, wonderful, seamless,",
                "  delve into, dive deep, navigate the, consider implementing, consider exploring,",
                "  rigorous, valuable insights, furthermore, moreover, nonetheless, in essence,",
                "  it's worth noting, needless to say, at the end of the day, great question,",
                "  feel free to, let me know if, happy to help, i hope this helps,",
                "  meaningful connections, meaningful results, recognizing your value, broadcasting your,",
                "  contributing to conversations, engaging with users, starting from scratch,",
                "  once people start, instead of just, especially if you're.",
                "- MATCH THE FORMAT OF THE QUESTION. If someone asks 'how long did it take', give a timeframe — not a lecture. If they ask a yes/no, start with yes or no. If the question is short, the reply should be short. Don't pad a one-line question into three sentences of advice.",
                "- NEVER give a three-sentence advice lecture in response to a personal experience question. If someone asks 'how long did X take you', say something like 'took me about 4 months tbh' — not a breakdown of best practices.",
                "- NEVER write 'consider [doing X]'. That is documentation/tutorial language. Real people say what they know from experience, not what someone should 'consider'. BAD: 'consider using asset pooling or dynamic loading techniques'. GOOD: 'asset pooling helped a lot when i had the same problem' or just 'yeah lag with that many assets is brutal, usually a memory issue'.",
                "- NEVER end with a motivational closer. Real redditors do not wrap up with encouragement like 'every bit of optimization can make a difference' or 'small changes add up' or 'it goes a long way'. End on a concrete observation or just stop.",
                "- THE MODERATOR TEST: if your reply has this shape — (1) acknowledge the problem, (2) give a structured 'consider doing X' tip, (3) end with a general truth — a mod WILL flag it as AI. This is the most common bot pattern on Reddit. Break up the structure. Be messy. Be one-sided. Say you've been there, or say it's a pain, or ask something specific. Don't be a helpful tutorial.",
                "- REAL EXAMPLE OF WHAT GOT CAUGHT: 'building a game like that with AI is wild, especially managing all those unique assets. lag can definitely be a nightmare, but consider using some asset pooling or dynamic loading techniques to help. every bit of optimization can make a difference as you scale up your environment.' — This got flagged by a mod. Three-part structure, 'consider using', 'make a difference as you scale up'. Never write anything like this.",
                "- DO NOT be overly nice, excited, or complimentary. Real redditors disagree, push back, qualify, add caveats. They don't cheerlead.",
                "- DO have an opinion or a concrete tip. Be a peer, not a TA grading homework.",
                "- LOWERCASE casual fragments are fine ('yeah this depends a lot on your stack'). Light typos / dropped articles read as human.",
                "- Sentence length should vary. NEVER write three sentences that each build on the last in a tidy escalating structure — that is the single most obvious AI pattern on Reddit. Real comments are uneven: one short thought, maybe one longer one, done.",
                "- DO NOT default to ending with a question. Most replies should end with a concrete observation, tip, take, or small anecdote, NOT a question. Only end with a question about 1 in 4 replies — and only if it genuinely advances the thread (not as engagement bait).",
                "- Vary your endings: (a) a concrete tip, (b) a direct take/opinion, (c) a small observation about a tradeoff, (d) a useful caveat, (e) a relevant follow-up question. Do NOT use pattern (e) by default.",
                "- Casual personal experience is fine and human-sounding ('tried this last month', 'ran into this when...'). Do NOT make up specific employers, products you built, or measurable claims about your own work.",
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

    def _voice_examples_lines(self, subreddit: str | None = None) -> list[str]:
        """Return prompt lines showing real scraped Reddit comments as voice examples.

        Falls back to a small set of hardcoded examples if the cache is empty
        (e.g. first run before the learning worker has scraped anything).
        """
        real = self.voice_sampler.sample(n=6, subreddit=subreddit)
        if real:
            lines = ["EXAMPLES of how real people in these communities actually write (these are real scraped comments — match this voice exactly):"]
            for ex in real:
                lines.append(f"  - '{ex}'")
            lines.append("")
            lines.append("Notice: no em dashes, no exclamation marks, fragments are fine, no tidy wrap-up, no praise, just a direct take or tip.")
        else:
            # Fallback if cache is empty
            lines = [
                "EXAMPLES of how real redditors actually write (study voice, sentence shape, length, casualness):",
                "  - 'eh, depends. for my setup the bottleneck is always io, not the model itself'",
                "  - 'agree on the second part but honestly the first one is overstated imo'",
                "  - 'tried this last month and it broke as soon as i hit ~10k tokens. ymmv'",
                "  - 'not really. you can do the same thing with a few lines of bash, no need for a tool'",
                "  - 'kinda. works ok for small projects but falls apart once you have >5 contributors'",
                "  - 'biggest gotcha is the cold-start latency. once it's warm it's fine'",
                "",
                "Notice: no em dashes, no exclamation marks, fragments are normal, no transitions, no wrap-up, just signal.",
            ]
        return lines

    def _normalize_candidate(self, candidate: str, promotion_mode: PromotionMode):
        normalized = " ".join(candidate.split()).strip()
        normalized = self._strip_ai_tells(normalized)
        if promotion_mode == PromotionMode.DISCLOSED_MONETIZED:
            disclosure = disclosure_for_mode(promotion_mode)
            if disclosure and disclosure not in normalized:
                normalized = f"{normalized} {disclosure}".strip()
        return normalized

    @staticmethod
    def _strip_ai_tells(text: str) -> str:
        """Remove typographic / phrasing tics that scream LLM."""
        # Smart punctuation -> ASCII. Em-dashes are the loudest tell; replace
        # with ", " unless they're already at a boundary.
        replacements = {
            "—": ", ",   # em dash —
            "–": ", ",   # en dash –
            "‘": "'",    # left single quote
            "’": "'",    # right single quote / apostrophe
            "“": '"',    # left double quote
            "”": '"',    # right double quote
            "…": "...",  # ellipsis
            ";": ".",    # semicolons read as AI / essay-formal on Reddit
            " ": " ",    # non-breaking space
        }
        for find, repl in replacements.items():
            text = text.replace(find, repl)
        # Collapse any double-comma / double-space artifacts from the em-dash replacement.
        text = text.replace(", ,", ",").replace(",,", ",")
        text = " ".join(text.split())
        # Drop exclamation marks (the bot doesn't need to be excited).
        text = text.replace("!", ".")
        # Collapse repeated periods that the exclamation->period swap may have created.
        while ".." in text and "..." not in text:
            text = text.replace("..", ".")
        return text.strip()

    def _is_usable_candidate(self, candidate: str, promotion_mode: PromotionMode, raw_candidate: str | None = None):
        if not candidate or len(candidate.split()) < MIN_REPLY_WORDS:
            return False
        if self._is_too_long(candidate):
            return False
        if raw_candidate and (self._has_paragraph_break(raw_candidate) or self._has_list_markers(raw_candidate)):
            return False
        candidate_lower = candidate.lower()
        if "http" in candidate_lower or "www." in candidate_lower:
            return False
        if "someone mentioned" in candidate_lower:
            return False
        # AI-cheerleader patterns that get called out as bot in the wild.
        ai_tells = (
            "it sounds like you",
            "it's great to see",
            "it is great to see",
            "it's exciting to see",
            "it's fascinating",
            "it's crucial to",
            "it is crucial to",
            "such details",
            "valuable insights",
            "keep up the",
            "keep up that",
            "i appreciate you",
            "i hope this helps",
            "feel free to",
            "let me know if",
            "fascinating perspective",
            "intriguing point",
            "navigate the",
            "ensure a seamless",
            "indeed,",
            "undeniably",
            "ultimately,",
            "in summary",
            "in conclusion",
            "noteworthy",
            "wonderful",
            "consider implementing",
            "consider exploring",
            "delve into",
            "dive deep",
            "dive into",
            "rigorous exploration",
            "leverage",
            "utilize",
            "streamline",
            "holistic",
            "synergy",
            "pivotal",
            "paramount",
            "empower",
            "foster",
            "resonate",
            "transformative",
            "groundbreaking",
            "revolutionary",
            "cutting-edge",
            "furthermore",
            "moreover",
            "nonetheless",
            "it's worth noting",
            "needless to say",
            "in essence",
            "essentially,",
            "at the end of the day",
            "this is a great",
            "great question",
            "happy to help",
            "absolutely,",
            "certainly,",
            "of course,",
            "meaningful connections",
            "meaningful results",
            "recognizing your value",
            "broadcasting your",
            "contributing to conversations",
            "engaging with users",
            "once people start recognizing",
            "starting from scratch",
            "instead of just broadcasting",
            # Phrases that got us called a bot in the wild
            "is real",
            "keeping it authentic",
            "staying true to your voice",
            "natural flow",
            "connect better with your audience",
            "overly polished",
            "authentic voice",
            "staying authentic",
            "genuine connection",
            "that sounds like an interesting",
            "sounds like an interesting approach",
            "invaluable",
            "in meaningful ways",
            "shape product development",
            "usability insights",
            "initial usability",
            "overall direction",
            "refining features",
            "product development in",
            "establish initial",
            # "consider [doing X]" — tutorial/documentation language, not Reddit language
            "consider using",
            "consider adding",
            "consider switching",
            "consider implementing",
            "consider leveraging",
            "consider adopting",
            "consider looking into",
            "consider checking out",
            "consider trying",
            "consider applying",
            # Corporate scaling language
            "as you scale",
            "scale up your",
            "scaling up your",
            "scale up the",
            "as it scales",
            # Motivational closers — the single most obvious AI tell
            "every bit of",
            "every little bit",
            "small changes add up",
            "adds up over time",
            "goes a long way",
            "makes a real difference",
            "can make a difference",
            "make all the difference",
            "makes all the difference",
            "pays off in the long",
            "worth the effort",
            "in the long run",
            # "to help" as a sentence-ending phrase
            "techniques to help",
            "tools to help",
            "methods to help",
            "strategies to help",
            "approaches to help",
            # Structured advice language
            "when it comes to optimization",
            "when it comes to performance",
            "one way to approach",
            "a good approach is",
            "a great way to",
            "a solid approach",
            "one solid",
            "a key thing to",
            "the key is to",
            "the trick is to",
            "the best approach",
            "the best way to handle",
            "asset pooling",
            "dynamic loading",
            # Essay / lecture-style patterns
            "transitioning from",
            "the reality of",
            "it's a reminder",
            "it is a reminder",
            "matters just as much",
            "beneath the surface",
            "in real-world",
            "in the real world",
            "robustness in",
            "doesn't guarantee",
            "does not guarantee",
            "expose critical",
            "exposes critical",
            "the foundation matters",
            "underscores the",
            "underscoring",
            "highlights the importance",
            "highlights the need",
            "speaks to the",
            "is a testament",
            "at its core",
        )
        if any(tell in candidate_lower for tell in ai_tells):
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
        # Only append a follow-up question on ~25% of replies, distributed deterministically
        # by thread id so the same thread always gets the same treatment (idempotent).
        # Use hashlib for cross-run stability (Python's hash() varies per process).
        should_ask_question = hashlib.md5(thread.thread_id.encode()).digest()[0] % 4 == 0
        if should_ask_question:
            question = self._follow_up_question(thread)
            if question and decision.promotion_mode != PromotionMode.DISCLOSED_MONETIZED and len(sentences) < MAX_REPLY_SENTENCES:
                sentences.append(question)
        return " ".join(sentences).strip()

    def _pick_variant(self, options: list[str], thread: ThreadContext, salt: str = "") -> str:
        """Deterministically pick one variant for this thread (idempotent + varied)."""
        if not options:
            return ""
        seed = (thread.thread_id + "|" + salt).encode()
        idx = hashlib.md5(seed).digest()[0] % len(options)
        return options[idx]

    def _acknowledge(self, thread: ThreadContext):
        text = (thread.target_comment.body if thread.target_comment else thread.post.title).lower()
        if "lose" in text:
            return self._pick_variant(
                [
                    "losing good prompts is almost always a storage problem, not a model problem",
                    "yeah this happens a lot, usually it's about where the prompts actually live",
                    "most of the time it comes down to storage habit, not the quality of the prompt itself",
                ],
                thread,
                salt="ack_lose",
            )
        if "compare" in text or " vs " in text:
            return self._pick_variant(
                [
                    "depends more on how your day-to-day looks than the feature list tbh",
                    "most of these comparisons come down to retrieval speed and how easy it is to find stuff later",
                    "what matters is which one fits how you actually work, not how it looks in a demo",
                ],
                thread,
                salt="ack_compare",
            )
        if "?" in text:
            return self._pick_variant(
                [
                    "the answer kind of depends on where the friction is right now",
                    "hard to say without knowing what part of the workflow is breaking",
                    "depends on your setup but usually the bottleneck is earlier than people think",
                ],
                thread,
                salt="ack_q",
            )
        return self._pick_variant(
            [
                "the tool matters less than the habit around it honestly",
                "usually comes down to workflow more than which tool you pick",
                "setup is less important than how consistently you actually use it",
            ],
            thread,
            salt="ack_default",
        )

    def _advice(self, thread: ThreadContext, strategy: ResponseStrategy, memory_context: MemoryContext):
        if self._memory_prefers_specificity(memory_context):
            return self._pick_variant(
                [
                    "specific examples usually land way better than broad advice in these threads",
                    "concrete details beat general tips here, people want to know what actually worked",
                    "the more specific the better, generic advice gets ignored pretty fast",
                ],
                thread,
                salt="adv_spec",
            )
        if strategy == ResponseStrategy.COMPARATIVE:
            return self._pick_variant(
                [
                    "the real test is whether you can find something that worked three weeks ago without digging",
                    "retrieval speed and tagging matter more than the feature list imo",
                    "most of the differences come down to how easy it is to rediscover old prompts, not the ui",
                ],
                thread,
                salt="adv_comp",
            )
        if strategy == ResponseStrategy.EXPERIENTIAL:
            return self._pick_variant(
                [
                    "keeping a small note next to each prompt about what didn't work saves way more time than the prompt itself",
                    "i just keep the prompt + a one-liner about why it worked. simple but it actually sticks",
                    "treating each run like a tiny experiment with notes tends to be the thing that clicks",
                ],
                thread,
                salt="adv_exp",
            )
        if strategy == ResponseStrategy.RESOURCE_LINKING:
            return self._pick_variant(
                [
                    "private storage, reusable templates, and community discovery are actually three different problems",
                    "worth splitting out personal storage vs team sharing vs public discovery, they need different things",
                    "three separate problems hiding in here: storing your own, reusing templates, finding what others built",
                ],
                thread,
                salt="adv_link",
            )
        return self._pick_variant(
            [
                "even a quick note on which model and prompt combo worked is a big step up from nothing",
                "jot down the prompt, the model, and what it was for. that's usually enough to reuse it later",
                "tagging with the rough use case saves a lot of reinventing the same thing",
                "saving it with a one-line note on when it worked is usually enough structure",
                "the model matters too, same prompt can behave really differently across versions",
            ],
            thread,
            salt="adv_default",
        )

    def _memory_prefers_specificity(self, memory_context: MemoryContext):
        memory_text = memory_context.prompt_text.lower()
        return "more specific" in memory_text or "prioritize specificity" in memory_text

    def _memory_caution(self, memory_context: MemoryContext):
        removals = sum(int(entry.metrics.get("removals", 0)) for entry in memory_context.daily_entries)
        negative_rewards = sum(int(entry.metrics.get("negative_rewards", 0)) for entry in memory_context.daily_entries)
        if removals or negative_rewards:
            return "keep it practical and skip the tool mention unless it obviously fits."
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
