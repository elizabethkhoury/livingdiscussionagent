from __future__ import annotations

from src.domain.models import RedditCommentCandidate, ThreadContext

# Author names that are always bots / mod accounts. Lowercase comparison.
BOT_AUTHORS = {
    "automoderator",
    "[deleted]",
    "[removed]",
    "",
}

# Phrases that strongly signal a comment was posted automatically (not a human).
BOT_BODY_SIGNATURES = (
    "i am a bot",
    "i'm a bot",
    "this action was performed automatically",
    "performed automatically by",
    "this is an automated",
    "beep boop",
    "contact the moderators of this subreddit",
)


def is_bot_comment(comment: RedditCommentCandidate) -> bool:
    """Return True if this comment is from a bot / moderator account.

    We skip replying directly to bots because (a) the reply is wasted — bots
    don't engage back, (b) it looks unnatural to other readers, and (c) AutoMod
    sticky comments are usually just rules / boilerplate, not real discussion.
    """
    author_lower = (comment.author or "").strip().lower()
    if author_lower in BOT_AUTHORS:
        return True
    # Reddit convention: many bot accounts end in "bot" or "-bot"
    if author_lower.endswith("bot") or author_lower.endswith("-bot"):
        return True
    body_lower = (comment.body or "").lower()
    if any(sig in body_lower for sig in BOT_BODY_SIGNATURES):
        return True
    return False


class CandidateSelector:
    def select(self, thread: ThreadContext):
        # Only consider real human comments as reply targets. Filter out bots
        # like AutoModerator, [deleted], and accounts whose names end in "bot".
        human_comments = [c for c in thread.comments if not is_bot_comment(c)]

        contexts = [ThreadContext(post=thread.post, comments=thread.comments, target_comment=None)]
        contexts.extend(
            ThreadContext(post=thread.post, comments=thread.comments, target_comment=comment)
            for comment in human_comments[:3]
        )
        return contexts
