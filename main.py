from __future__ import annotations

import argparse
import asyncio

import uvicorn

from src.app.logging import configure_logging
from src.app.settings import get_settings
from src.review.api import create_review_app
from src.storage.db import Base, engine
from src.workers.ingest_worker import IngestWorker
from src.workers.learning_worker import LearningWorker
from src.workers.monitor_worker import MonitorWorker
from src.workers.review_worker import ReviewWorker


def bootstrap():
    Base.metadata.create_all(bind=engine)


def build_parser():
    parser = argparse.ArgumentParser(description="PromptHunt Reddit agent")
    parser.add_argument(
        "command",
        choices=["bootstrap", "dashboard", "ingest-once", "review-once", "monitor-once", "learn-once"],
    )
    return parser


async def run_async_command(command: str):
    if command == "bootstrap":
        bootstrap()
        return {"status": "ok", "command": command}
    if command == "ingest-once":
        bootstrap()
        return IngestWorker().run_once()
    if command == "review-once":
        bootstrap()
        return await ReviewWorker().run_once()
    if command == "monitor-once":
        bootstrap()
        return MonitorWorker().run_once()
    if command == "learn-once":
        bootstrap()
        return LearningWorker().run_once()
    raise ValueError(f"Unknown command: {command}")


def main():
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "dashboard":
        bootstrap()
        settings = get_settings()
        uvicorn.run(create_review_app(), host=settings.app_host, port=settings.app_port)
        return
    result = asyncio.run(run_async_command(args.command))
    if result is not None:
        print(result)


if __name__ == "__main__":
    main()
