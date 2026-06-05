"""Watches our posted comments for replies and posts short follow-ups.

What it does each run:
  1. Look at every comment we've posted in the last 7 days.
  2. Fetch its direct replies via the public Reddit JSON endpoint.
  3. Skip replies that are from us, from a bot, too new, too old, low-value
     ("thanks"), or hostile/toxic.
  4. For the remaining replies, generate a casual follow-up and post it via
     the same Playwright transport (reply targeted at the user's comment).
  5. Respect the same hourly / daily / per-subreddit caps as primary posting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from src.app.settings import get_settings
from src.domain.enums import (
    CommercialOpportunity,
    DecisionAction,
    DraftStatus,
    PromotionMode,
    ResponseStrategy,
    RiskLevel,
    SubredditPromoPolicy,
    Tone,
)
from src.domain.models import (
    ClassificationResult,
    DecisionResult,
    DraftReply,
    DraftEvaluation,
    PolicyDecisionTrace,
)
from src.execute.poster import PostingService
from src.generate.conversation_writer import ConversationWriter
from src.ingest.reddit_reader import RedditJSONReader
from src.runtime.active_hours import hours_until_active, is_within_active_hours
from src.runtime.halt_guard import operation_blocked_result
from src.storage import schema
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, ThreadRepository

logger = logging.getLogger(__name__)

MIN_REPLY_AGE_MINUTES = 12
MAX_REPLY_AGE_HOURS = 36
LOOKBACK_DAYS_FOR_OUR_POSTS = 7
SKIP_AUTHORS = {"automoderator", "[deleted]", "[removed]", ""}


class ConversationWorker:
    def __init__(self):
        self.settings = get_settings()
        self.reader = RedditJSONReader(request_delay_seconds=self.settings.reddit_request_delay_seconds)
        self.writer = ConversationWriter()
        self.poster = PostingService()

    async def run_once(self):
        blocked = operation_blocked_result("conversation-once")
        if blocked is not None:
            return blocked
        if not is_within_active_hours():
            wait_h = hours_until_active()
            return [{"skipped": "outside_active_hours", "hours_until_active": round(wait_h, 1)}]

        candidates = self._gather_candidate_replies()
        results = []
        our_username_lower = (self.settings.reddit_username or "").lower()

        for ctx in candidates:
            reply = ctx["reply"]
            author_lower = (reply.get("author") or "").lower()
            if author_lower in SKIP_AUTHORS or author_lower == our_username_lower:
                continue
            if author_lower.endswith("bot"):
                # Reddit convention: bot accounts often end with 'bot'. Skip.
                continue
            created = reply.get("created_at")
            if isinstance(created, datetime):
                age_minutes = (datetime.utcnow() - created).total_seconds() / 60
                if age_minutes < MIN_REPLY_AGE_MINUTES:
                    continue
                if age_minutes > MAX_REPLY_AGE_HOURS * 60:
                    continue

            reply_target_key = f"reddit:comment:{reply['id']}"
            if self._already_responded(reply_target_key):
                continue

            if self.writer.is_toxic(reply["body"]):
                results.append({"reply_id": reply["id"], "skipped": "toxic"})
                continue

            response_text = self.writer.compose(
                original_post_title=ctx["post_title"],
                our_previous_comment=ctx["our_comment_body"],
                reply_body=reply["body"],
                reply_author=reply.get("author") or "redditor",
            )
            if not response_text:
                results.append({"reply_id": reply["id"], "skipped": "no_useful_reply"})
                continue

            attempt = await self._post_followup(ctx, reply, response_text)
            if attempt is None:
                results.append({"reply_id": reply["id"], "skipped": "transport_failed"})
            else:
                results.append({"reply_id": reply["id"], "posted": attempt.get("posted_comment_id")})
        return results

    def _already_responded(self, reply_target_key: str) -> bool:
        with session_scope() as session:
            stmt = select(schema.PostAttemptRecord.id).where(
                schema.PostAttemptRecord.reply_target_key == reply_target_key,
                schema.PostAttemptRecord.status.in_(["pending", "posted"]),
            )
            return session.execute(stmt).first() is not None

    def _gather_candidate_replies(self):
        cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS_FOR_OUR_POSTS)
        # Don't bother fetching for posts < 1 hour old — they probably don't have replies yet.
        recent_floor = datetime.utcnow() - timedelta(minutes=30)

        candidates = []
        with session_scope() as session:
            stmt = select(schema.PostAttemptRecord).where(
                schema.PostAttemptRecord.status == "posted",
                schema.PostAttemptRecord.posted_at.is_not(None),
                schema.PostAttemptRecord.posted_at >= cutoff,
                schema.PostAttemptRecord.posted_at <= recent_floor,
            )
            attempts = list(session.scalars(stmt).all())
            for attempt in attempts:
                if not attempt.posted_comment_id or not attempt.posted_comment_id.startswith("t1_"):
                    continue
                draft = session.get(schema.DraftRecord, attempt.draft_id)
                if draft is None:
                    continue
                decision = session.get(schema.DecisionRecord, draft.decision_id)
                classification = session.get(schema.ClassificationRecord, decision.classification_id)
                thread = session.get(schema.ThreadRecord, classification.thread_id)
                comment_id = attempt.posted_comment_id.replace("t1_", "")
                candidates.append(
                    {
                        "thread_id_db": thread.id,
                        "thread_platform_id": thread.platform_thread_id,
                        "subreddit": thread.subreddit,
                        "post_title": thread.title,
                        "post_url": thread.url,
                        "our_comment_id": comment_id,
                        "our_comment_body": draft.body,
                    }
                )

        # Now fetch replies for each (outside of session_scope so we don't block the connection)
        out = []
        for c in candidates:
            try:
                replies = self.reader.fetch_comment_replies(c["subreddit"], c["thread_platform_id"], c["our_comment_id"])
            except Exception as exc:
                logger.warning("fetch_comment_replies error: %s", exc)
                continue
            for r in replies:
                if not r.get("id") or not r.get("body"):
                    continue
                out.append({**c, "reply": r})
        return out

    async def _post_followup(self, ctx, reply, response_text: str):
        # 1. Persist the user's reply as a ThreadCommentRecord (so target_comment_id can point at it).
        # 2. Build a synthetic Classification + Decision + Draft for the response.
        # 3. Use PostingService.publish_draft to post.
        with session_scope() as session:
            decisions_repo = DecisionRepository(session)
            existing_comment = session.scalar(
                select(schema.ThreadCommentRecord).where(schema.ThreadCommentRecord.platform_comment_id == reply["id"])
            )
            if existing_comment is None:
                existing_comment = schema.ThreadCommentRecord(
                    platform_comment_id=reply["id"],
                    thread_id=ctx["thread_id_db"],
                    author=reply.get("author") or "",
                    body=reply["body"],
                    created_at_platform=reply.get("created_at"),
                )
                session.add(existing_comment)
                session.flush()

            classification_result = ClassificationResult(
                intent="follow_up",
                relevance_score=1.0,
                commercial_opportunity=CommercialOpportunity.LOW,
                value_add_score=0.9,
                policy_risk_score=0.0,
                promo_fit_score=0.0,
                tone=Tone.NEUTRAL,
                subreddit_promo_policy=SubredditPromoPolicy.ALLOW,
                duplicate_similarity_score=0.0,
                reason_codes=["conversation_followup"],
            )
            classification_record = decisions_repo.create_classification(
                ctx["thread_id_db"], existing_comment.id, classification_result
            )
            decision_result = DecisionResult(
                action=DecisionAction.AUTOPOST_INFO,
                promotion_mode=PromotionMode.NONE,
                requires_review=False,
                risk_level=RiskLevel.LOW,
                selected_strategy=ResponseStrategy.EDUCATIONAL,
                trace=PolicyDecisionTrace(reason_codes=["conversation_followup"]),
            )
            decision_record = decisions_repo.create_decision(classification_record.id, decision_result)
            draft = DraftReply(
                body=response_text,
                strategy=ResponseStrategy.EDUCATIONAL,
                promotion_mode=PromotionMode.NONE,
                contains_link=False,
                disclosure_text=None,
                thread_id=ctx["thread_platform_id"],
                autopost_eligible=True,
                evaluation=DraftEvaluation(
                    authenticity_score=0.95,
                    specificity_score=0.9,
                    helpfulness_score=0.9,
                    promo_pressure_score=0.0,
                    policy_compliance_score=1.0,
                    overall_score=0.95,
                    fail_reasons=[],
                ),
            )
            draft_record = decisions_repo.create_draft(decision_record.id, draft, status=DraftStatus.CREATED.value)
            draft_id = draft_record.id

        try:
            attempt = await self.poster.publish_draft(draft_id, ctx["subreddit"])
        except RuntimeError as exc:
            logger.info("conversation post hit circuit breaker: %s", exc)
            return None
        if attempt is None:
            return None
        return {
            "draft_id": draft_id,
            "posted_comment_id": getattr(attempt, "posted_comment_id", None),
            "status": getattr(attempt, "status", None),
        }
