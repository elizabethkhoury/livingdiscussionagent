from __future__ import annotations

from src.domain.models import ThreadContext


class CandidateSelector:
    def select(self, thread: ThreadContext):
        contexts = [ThreadContext(post=thread.post, comments=thread.comments, target_comment=None)]
        contexts.extend(ThreadContext(post=thread.post, comments=thread.comments, target_comment=comment) for comment in thread.comments[:3])
        return contexts
