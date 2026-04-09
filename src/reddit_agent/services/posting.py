from __future__ import annotations

from reddit_agent.models import ActionType, DraftStatus
from reddit_agent.repository import Repository


class PostingService:
    def __init__(self, reddit_browser_poster):
        self.reddit_browser_poster = reddit_browser_poster

    async def post_approved_draft(self, *, repository: Repository, action_id: str):
        action = await repository.get_action(action_id)
        if action is None:
            raise ValueError('Post action not found.')
        draft = await repository.get_draft(action.draft_id) if action.draft_id else None
        candidate = await repository.get_candidate(action.candidate_id)
        if draft is None or candidate is None:
            raise ValueError('Draft or candidate missing for post action.')

        started = await repository.create_action(
            candidate.id,
            ActionType.posting_started.value,
            draft_id=draft.id,
            notes='Kernel browser posting started.',
            payload={'requested_action_id': action.id},
        )
        await repository.session.commit()

        result = await self.reddit_browser_poster.post_reply(
            permalink=candidate.permalink,
            body=draft.body,
        )

        if result['status'] == 'posted':
            draft.status = DraftStatus.posted.value
            posted = await repository.create_action(
                candidate.id,
                ActionType.posted.value,
                draft_id=draft.id,
                notes='Approved draft posted through Kernel browser.',
                payload={
                    'external_comment_url': result.get('comment_url'),
                    'session_id': result['diagnostics'].get('session_id'),
                    'live_view_url': result['diagnostics'].get('live_view_url'),
                    'requested_action_id': action.id,
                    'started_action_id': started.id,
                    'diagnostics': result['diagnostics'],
                },
            )
            await repository.session.commit()
            return posted

        failed = await repository.create_action(
            candidate.id,
            ActionType.post_failed.value,
            draft_id=draft.id,
            notes='Kernel browser post attempt failed.',
            payload={
                'failure_reason': result['status'],
                'auth_required': result['status'] == 'auth_required',
                'requested_action_id': action.id,
                'started_action_id': started.id,
                'diagnostics': result.get('diagnostics', {}),
            },
        )
        await repository.session.commit()
        return failed
