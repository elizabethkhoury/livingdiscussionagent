from __future__ import annotations

import asyncio

from temporalio.client import Client

from reddit_agent.db import SessionLocal
from reddit_agent.repository import Repository
from reddit_agent.services.posting import PostingService
from reddit_agent.settings import Settings


class PostingDispatcher:
    def __init__(self, settings: Settings, posting_service: PostingService):
        self.settings = settings
        self.posting_service = posting_service

    async def dispatch(self, action_id: str):
        try:
            from reddit_agent.workflows.temporal import PostApprovedDraftWorkflow

            client = await Client.connect(self.settings.temporal_target)
            await client.start_workflow(
                PostApprovedDraftWorkflow.run,
                action_id,
                id=f'post-approved-draft-{action_id}',
                task_queue=self.settings.temporal_task_queue,
            )
            return 'temporal'
        except Exception:
            asyncio.create_task(self._run_locally(action_id))
            return 'local'

    async def _run_locally(self, action_id: str):
        async with SessionLocal() as session:
            repository = Repository(session)
            await self.posting_service.post_approved_draft(
                repository=repository,
                action_id=action_id,
            )
