from __future__ import annotations

from difflib import SequenceMatcher

from src.app.settings import get_settings
from src.classify.pipeline import ClassificationPipeline
from src.decide.engine import RuleBasedDecisionEngine
from src.domain.enums import DecisionAction
from src.generate.draft_writer import DraftWriter
from src.generate.evaluators import DraftEvaluator
from src.ingest.candidate_selector import CandidateSelector
from src.ingest.reddit_reader import RedditJSONReader
from src.runtime.halt_guard import operation_blocked_result
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, ThreadRepository


class IngestWorker:
    def __init__(self):
        self.settings = get_settings()
        self.reader = RedditJSONReader(request_delay_seconds=self.settings.reddit_request_delay_seconds)
        self.selector = CandidateSelector()
        self.decision_engine = RuleBasedDecisionEngine()
        self.draft_writer = DraftWriter()
        self.draft_evaluator = DraftEvaluator()

    def run_once(self):
        blocked = operation_blocked_result("ingest-once")
        if blocked is not None:
            return blocked
        processed = []
        recently_classified_thread_ids = self._recently_classified_thread_ids()
        for subreddit in self._enabled_subreddits():
            for post in self.reader.fetch_posts(subreddit, limit=self.settings.reddit_posts_per_subreddit):
                if self.reader.rate_limited:
                    break
                if post.age_hours > 24:
                    continue
                if post.platform_thread_id in recently_classified_thread_ids:
                    continue
                full_thread = self.reader.fetch_thread_context(post, comment_limit=self.settings.reddit_comment_limit)
                if self.reader.rate_limited:
                    break
                with session_scope() as session:
                    threads = ThreadRepository(session)
                    prior_bodies = threads.recent_post_bodies()
                classifier = ClassificationPipeline(
                    duplicate_similarity_lookup=lambda candidate, prior_bodies=tuple(prior_bodies): self._duplicate_similarity(candidate.combined_text, list(prior_bodies))
                )
                candidates = []
                for candidate in self.selector.select(full_thread):
                    classification = classifier.classify(candidate)
                    decision = self.decision_engine.decide(candidate, classification)
                    candidates.append((candidate, classification, decision))
                candidate, classification, decision = self._best_candidate(candidates)
                draft = self.draft_writer.compose(candidate, decision)
                if draft:
                    draft.evaluation = self.draft_evaluator.evaluate(candidate, draft)
                processed.append(self._persist(candidate, classification, decision, draft))
                recently_classified_thread_ids.add(post.platform_thread_id)
            if self.reader.rate_limited:
                break
        return processed

    def _enabled_subreddits(self):
        seen = set()
        subreddits = []
        for subreddit in self.settings.enabled_subreddits:
            key = subreddit.lower()
            if key in seen:
                continue
            seen.add(key)
            subreddits.append(subreddit)
        return subreddits

    def _recently_classified_thread_ids(self):
        with session_scope() as session:
            threads = ThreadRepository(session)
            return threads.recently_classified_platform_thread_ids(hours=self.settings.reddit_reprocess_after_hours) | threads.posted_thread_ids()

    def _best_candidate(self, candidates):
        return max(candidates, key=lambda item: self._candidate_rank(*item))

    def _candidate_rank(self, candidate, classification, decision):
        action_rank = {
            DecisionAction.SKIP: 0,
            DecisionAction.AUTOPOST_INFO: 1,
            DecisionAction.QUEUE_REVIEW_RISKY: 2,
            DecisionAction.QUEUE_REVIEW_PRODUCT: 3,
        }.get(decision.action, 0)
        return (
            action_rank,
            classification.value_add_score,
            classification.promo_fit_score,
            classification.relevance_score,
            -classification.policy_risk_score,
            candidate.target_comment is None,
        )

    def _duplicate_similarity(self, text: str, prior_bodies: list[str]):
        if not prior_bodies:
            return 0.0
        best = 0.0
        for prior_body in prior_bodies:
            best = max(best, SequenceMatcher(a=text.lower(), b=prior_body.lower()).ratio())
        return round(best, 3)

    def _persist(self, candidate, classification, decision, draft):
        with session_scope() as session:
            threads = ThreadRepository(session)
            decisions = DecisionRepository(session)
            thread_record = threads.upsert_thread(candidate)
            target_comment_id = None
            if candidate.target_comment:
                target_comment = next(comment for comment in thread_record.comments if comment.platform_comment_id == candidate.target_comment.platform_comment_id)
                target_comment_id = target_comment.id
            classification_record = decisions.create_classification(thread_record.id, target_comment_id, classification)
            decision_record = decisions.create_decision(classification_record.id, decision)
            if draft is None:
                return {"thread_id": thread_record.id, "action": decision.action.value, "draft_id": None}
            draft_record = decisions.create_draft(decision_record.id, draft)
            if decision.requires_review:
                review = decisions.queue_review(draft_record.id, ",".join(decision.trace.reason_codes))
                return {
                    "thread_id": thread_record.id,
                    "action": decision.action.value,
                    "draft_id": draft_record.id,
                    "review_id": review.id,
                }
            return {"thread_id": thread_record.id, "action": decision.action.value, "draft_id": draft_record.id}
