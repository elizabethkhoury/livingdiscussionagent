from reddit_agent.models import MemoryType


def compact_memory(entries: list[str], limit: int = 5):
    if len(entries) <= limit:
        return entries
    head = entries[: limit - 1]
    tail = entries[-1]
    summary = f'Compacted {len(entries) - limit + 1} earlier lessons into one summary.'
    return [*head, summary, tail]


def memory_weight(memory_type: MemoryType):
    weights = {
        MemoryType.working: 0.7,
        MemoryType.episodic: 1.0,
        MemoryType.semantic: 1.25,
        MemoryType.identity: 1.4,
        MemoryType.health: 1.1,
    }
    return weights[memory_type]
