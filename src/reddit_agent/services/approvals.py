from __future__ import annotations

from reddit_agent.models import ApprovalDecision, DraftStatus
from reddit_agent.repository import Repository


class ApprovalService:
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
        if decision == ApprovalDecision.approve and candidate is not None:
            action = await repository.create_action(
                candidate.id,
                'manual_handoff',
                draft_id=draft.id,
                notes='Operator approved draft and should manually post on Reddit.',
                payload={'permalink': candidate.permalink, 'body': final_body},
            )
            handoff_url = candidate.permalink
            await repository.create_action(
                candidate.id,
                'manual_post_confirmed',
                draft_id=draft.id,
                notes='Placeholder confirmation event for manual posting workflow.',
                payload={'handoff_action_id': action.id},
            )
        await repository.session.commit()
        return draft, handoff_url
