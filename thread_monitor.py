from src.storage.db import session_scope
from src.storage.repositories import ThreadRepository


def already_replied(post_id: str):
    with session_scope() as session:
        repo = ThreadRepository(session)
        return post_id in repo.posted_thread_ids()


def mark_replied(post_id: str):
    return post_id
