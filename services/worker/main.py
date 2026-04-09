from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from reddit_agent.settings import get_settings
from reddit_agent.workflows.temporal import (
    AgentActivities,
    DiscoverCandidatesWorkflow,
    PostApprovedDraftWorkflow,
)


async def main():
    settings = get_settings()
    client = await Client.connect(settings.temporal_target)
    activities = AgentActivities()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[DiscoverCandidatesWorkflow, PostApprovedDraftWorkflow],
        activities=[
            activities.discover_candidates,
            activities.generate_drafts,
            activities.post_approved_draft,
        ],
    )
    await worker.run()


if __name__ == '__main__':
    asyncio.run(main())
