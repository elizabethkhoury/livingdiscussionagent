from __future__ import annotations

from difflib import SequenceMatcher

from src.app.settings import get_settings
from src.classify.pipeline import ClassificationPipeline
from src.decide.engine import RuleBasedDecisionEngine
from src.generate.draft_writer import DraftWriter
from src.generate.evaluators import DraftEvaluator
from src.ingest.candidate_selector import CandidateSelector
from src.ingest.reddit_reader import RedditJSONReader
from src.storage.db import session_scope
from src.storage.repositories import DecisionRepository, ThreadRepository


class IngestWorker:
    def __init__(self):
        self.settings = get_settings()
        self.reader = RedditJSONReader()
        self.selector = CandidateSelector()
        self.decision_engine = RuleBasedDecisionEngine()
        self.draft_writer = DraftWriter()
        self.draft_evaluator = DraftEvaluator()

    def run_once(self):
        processed = []
        for subreddit in self.settings.enabled_subreddits:
            for post in self.reader.fetch_posts(subreddit):
                if post.age_hours > 24:
                    continue
                full_thread = self.reader.fetch_thread_context(post)
                with session_scope() as session:
                    threads = ThreadRepository(session)
                    prior_bodies = threads.recent_post_bodies()
                classifier = ClassificationPipeline(
                    duplicate_similarity_lookup=lambda candidate, prior_bodies=tuple(prior_bodies): self._duplicate_similarity(candidate.combined_text, list(prior_bodies))
                )
                for candidate in self.selector.select(full_thread):
                    classification = classifier.classify(candidate)
                    decision = self.decision_engine.decide(candidate, classification)
                    draft = self.draft_writer.compose(candidate, decision)
                    if draft:
                        draft.evaluation = self.draft_evaluator.evaluate(candidate, draft)
                    processed.append(self._persist(candidate, classification, decision, draft))
        return processed

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
