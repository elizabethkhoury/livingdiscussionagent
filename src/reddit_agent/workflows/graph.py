from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from reddit_agent.repository import Repository
from reddit_agent.services.discovery import DiscoveryService
from reddit_agent.services.drafting import DraftingService


class CandidateGraphState(TypedDict, total=False):
    subreddit: str
    created_candidate_ids: list[str]
    queued_candidate_ids: list[str]
    draft_ids: list[str]


def build_discovery_graph(
    discovery_service: DiscoveryService, repository: Repository, subreddit_rules, product_rules
):
    async def discover(state: CandidateGraphState):
        rule = subreddit_rules[state['subreddit']]
        created = await discovery_service.sync_subreddit(
            repository=repository,
            subreddit_rule=rule,
            product_rules=product_rules,
        )
        return {
            'created_candidate_ids': [candidate.id for candidate in created],
            'queued_candidate_ids': [
                candidate.id for candidate in created if candidate.decision == 'queue_draft'
            ],
        }

    graph = StateGraph(CandidateGraphState)
    graph.add_node('discover', discover)
    graph.add_edge(START, 'discover')
    graph.add_edge('discover', END)
    return graph.compile()


def build_drafting_graph(drafting_service: DraftingService, repository: Repository):
    async def generate(state: CandidateGraphState):
        draft_ids = []
        for candidate_id in state.get('queued_candidate_ids', []):
            candidate = await repository.get_candidate(candidate_id)
            if candidate is None:
                continue
            draft = await drafting_service.generate(repository=repository, candidate=candidate)
            draft_ids.append(draft.id)
        return {'draft_ids': draft_ids}

    graph = StateGraph(CandidateGraphState)
    graph.add_node('generate', generate)
    graph.add_edge(START, 'generate')
    graph.add_edge('generate', END)
    return graph.compile()
