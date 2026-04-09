from reddit_agent.schemas import DraftRead, ReplayRead


def build_replay(candidate):
    drafts = [
        DraftRead(
            id=draft.id,
            candidate_id=draft.candidate_id,
            version=draft.version,
            body=draft.body,
            critic_notes=draft.critic_notes,
            token_usage=draft.token_usage,
            similarity_score=draft.similarity_score,
            status=draft.status,
            created_at=draft.created_at,
        )
        for draft in candidate.drafts
    ]
    return ReplayRead(
        candidate_id=candidate.id,
        title=candidate.title,
        subreddit=candidate.subreddit,
        decision=candidate.decision,
        route_product=candidate.route_product,
        trace=candidate.decision_trace,
        drafts=drafts,
    )
