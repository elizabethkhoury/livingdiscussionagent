from reddit_agent.schemas import ActionRead, DraftRead, ReplayRead


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
    actions = [
        ActionRead(
            id=action.id,
            action_type=action.action_type,
            notes=action.notes,
            payload=action.payload,
            created_at=action.created_at,
        )
        for action in sorted(candidate.actions, key=lambda item: item.created_at)
    ]
    return ReplayRead(
        candidate_id=candidate.id,
        title=candidate.title,
        subreddit=candidate.subreddit,
        decision=candidate.decision,
        route_product=candidate.route_product,
        trace=candidate.decision_trace,
        drafts=drafts,
        actions=actions,
    )
