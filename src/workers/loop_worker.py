from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import datetime

from src.learn.diary_builder import DiaryBuilder
from src.workers.conversation_worker import ConversationWorker
from src.workers.ingest_worker import IngestWorker
from src.workers.learning_worker import LearningWorker
from src.workers.monitor_worker import MonitorWorker
from src.workers.review_worker import ReviewWorker

logger = logging.getLogger(__name__)


class LoopWorker:
    """Runs ingest -> review -> monitor on a recurring schedule with jitter.

    Default cadence: ~15 minutes between cycles, jittered ±3 minutes.
    Stops gracefully on SIGINT/SIGTERM.
    """

    def __init__(self, base_interval_seconds: int = 900, jitter_seconds: int = 180):
        self.base_interval = base_interval_seconds
        self.jitter = jitter_seconds
        self._stop = asyncio.Event()

    def _install_signal_handlers(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass

    async def run_forever(self):
        self._install_signal_handlers()
        cycle = 0
        while not self._stop.is_set():
            cycle += 1
            started = datetime.utcnow()
            print(f"[loop] cycle {cycle} started at {started.isoformat()}Z")
            try:
                ingest_result = IngestWorker().run_once()
                print(f"[loop] ingest: {len(ingest_result) if isinstance(ingest_result, list) else ingest_result}")
            except Exception as exc:
                logger.exception("ingest failed: %s", exc)
                print(f"[loop] ingest failed: {exc}")

            try:
                review_result = await ReviewWorker().run_once()
                print(f"[loop] review: {len(review_result) if isinstance(review_result, list) else review_result}")
            except Exception as exc:
                logger.exception("review failed: %s", exc)
                print(f"[loop] review failed: {exc}")

            try:
                conversation_result = await ConversationWorker().run_once()
                print(f"[loop] conversation: {len(conversation_result) if isinstance(conversation_result, list) else conversation_result}")
            except Exception as exc:
                logger.exception("conversation failed: %s", exc)
                print(f"[loop] conversation failed: {exc}")

            try:
                monitor_result = MonitorWorker().run_once()
                print(f"[loop] monitor: {len(monitor_result) if isinstance(monitor_result, list) else monitor_result}")
            except Exception as exc:
                logger.exception("monitor failed: %s", exc)
                print(f"[loop] monitor failed: {exc}")

            # Run learning + diary memory occasionally (every ~6 cycles)
            if cycle % 6 == 0:
                try:
                    LearningWorker().run_once()
                    DiaryBuilder().update()
                    print("[loop] learning + diary updated")
                except Exception as exc:
                    logger.exception("learning failed: %s", exc)

            sleep_seconds = self.base_interval + random.randint(-self.jitter, self.jitter)
            sleep_seconds = max(60, sleep_seconds)
            print(f"[loop] sleeping {sleep_seconds}s until next cycle")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                pass
        print("[loop] stop requested, exiting cleanly")
