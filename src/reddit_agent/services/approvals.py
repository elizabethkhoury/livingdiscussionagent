from __future__ import annotations

from reddit_agent.models import ActionType, ApprovalDecision, DraftStatus
from reddit_agent.repository import Repository


class ApprovalService:
    def __init__(self, posting_dispatcher=None):
        self.posting_dispatcher = posting_dispatcher

    async def decide(
        self,
        *,
        repository: Repository,
        draft_id: str,
        decision: ApprovalDecision,
        operator_feedback: str | None,
        edited_body: str | None,
    ):
        draft = await repository.get_draft(draft_id)
        if draft is None:
            raise ValueError('Draft not found.')
        candidate = await repository.get_candidate(draft.candidate_id)
        final_body = edited_body or draft.body
        draft.body = final_body
        draft.status = (
            DraftStatus.approved.value
            if decision == ApprovalDecision.approve
            else DraftStatus.rejected.value
        )
        await repository.add_approval(
            draft_id=draft_id,
            decision=decision.value,
            operator_feedback=operator_feedback,
            edited_body=edited_body,
        )
        handoff_url = None
        post_action = None
        if decision == ApprovalDecision.approve and candidate is not None:
            post_action = await repository.create_action(
                candidate.id,
                ActionType.post_requested.value,
                draft_id=draft.id,
                notes='Operator approved draft. Browser posting queued.',
                payload={'permalink': candidate.permalink, 'body': final_body},
            )
            handoff_url = candidate.permalink
        await repository.session.commit()
        if post_action is not None and self.posting_dispatcher is not None:
            await self.posting_dispatcher.dispatch(post_action.id)
        return draft, handoff_url, post_action
