from __future__ import annotations

from datetime import datetime

from src.domain.enums import DraftStatus, ReviewStatus
from src.domain.models import ReviewItem
from src.storage import schema
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository


class ReviewService:
    def enqueue(self, draft_id: int, reason: str):
        with session_scope() as session:
            decisions = DecisionRepository(session)
            review = decisions.queue_review(draft_id, reason)
            return ReviewItem(
                review_id=review.id,
                draft_id=review.draft_id,
                status=ReviewStatus(review.status),
                review_reason=review.review_reason,
            )

    def approve(self, review_id: int, note: str | None = None, edited_body: str | None = None):
        with session_scope() as session:
            review = session.get(schema.ReviewRecord, review_id)
            if review is None:
                raise ValueError(f"Unknown review {review_id}")
            review.status = ReviewStatus.APPROVED.value
            review.reviewer_note = note
            review.reviewed_at = datetime.utcnow()
            draft = session.get(schema.DraftRecord, review.draft_id)
            if edited_body and draft:
                draft.body = edited_body
            if draft:
                draft.status = DraftStatus.APPROVED.value
            session.flush()
            return review

    def reject(self, review_id: int, note: str | None = None):
        with session_scope() as session:
            review = session.get(schema.ReviewRecord, review_id)
            if review is None:
                raise ValueError(f"Unknown review {review_id}")
            review.status = ReviewStatus.REJECTED.value
            review.reviewer_note = note
            review.reviewed_at = datetime.utcnow()
            draft = session.get(schema.DraftRecord, review.draft_id)
            if draft:
                draft.status = DraftStatus.REJECTED.value
            session.flush()
            return review
