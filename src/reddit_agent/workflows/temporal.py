from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from reddit_agent.bootstrap import get_runtime
    from reddit_agent.db import SessionLocal
    from reddit_agent.repository import Repository
    from reddit_agent.services.discovery import DiscoveryService
    from reddit_agent.services.drafting import DraftingService
    from reddit_agent.services.posting import PostingService
    from reddit_agent.workflows.graph import build_discovery_graph, build_drafting_graph


class AgentActivities:
    @activity.defn
    async def discover_candidates(self, subreddit: str):
        runtime = get_runtime()
        async with SessionLocal() as session:
            repository = Repository(session)
            discovery = DiscoveryService(
                reddit_browser_discovery=runtime['reddit_browser_discovery'],
                llm_provider=runtime['llm_provider'],
                lifecycle_rules=runtime['lifecycle_rules'],
            )
            graph = build_discovery_graph(
                discovery,
                repository,
                runtime['subreddit_rules'],
                runtime['product_rules'],
            )
            return await graph.ainvoke({'subreddit': subreddit})

    @activity.defn
    async def generate_drafts(self, queued_candidate_ids: list[str]):
        async with SessionLocal() as session:
            repository = Repository(session)
            graph = build_drafting_graph(DraftingService(get_runtime()['llm_provider']), repository)
            return await graph.ainvoke({'queued_candidate_ids': queued_candidate_ids})

    @activity.defn
    async def post_approved_draft(self, action_id: str):
        runtime = get_runtime()
        async with SessionLocal() as session:
            repository = Repository(session)
            posting = PostingService(runtime['reddit_browser_poster'])
            action = await posting.post_approved_draft(repository=repository, action_id=action_id)
            return {'action_id': action.id, 'action_type': action.action_type}


@workflow.defn
class DiscoverCandidatesWorkflow:
    @workflow.run
    async def run(self, subreddit: str):
        created = await workflow.execute_activity(
            AgentActivities.discover_candidates,
            subreddit,
            start_to_close_timeout=timedelta(minutes=2),
        )
        queued_ids = created.get('queued_candidate_ids', [])
        if not queued_ids:
            return created
        drafted = await workflow.execute_activity(
            AgentActivities.generate_drafts,
            queued_ids,
            start_to_close_timeout=timedelta(minutes=2),
        )
        return {**created, **drafted}


@workflow.defn
class PostApprovedDraftWorkflow:
    @workflow.run
    async def run(self, action_id: str):
        return await workflow.execute_activity(
            AgentActivities.post_approved_draft,
            action_id,
            start_to_close_timeout=timedelta(minutes=5),
        )
