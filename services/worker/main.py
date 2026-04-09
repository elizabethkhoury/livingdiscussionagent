from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from reddit_agent.settings import get_settings
from reddit_agent.workflows.temporal import AgentActivities, DiscoverCandidatesWorkflow


async def main():
    client = await Client.connect(get_settings().temporal_target)
    activities = AgentActivities()
    worker = Worker(
        client,
        task_queue='reddit-agent',
        workflows=[DiscoverCandidatesWorkflow],
        activities=[activities.discover_candidates, activities.generate_drafts],
    )
    await worker.run()


if __name__ == '__main__':
    asyncio.run(main())
