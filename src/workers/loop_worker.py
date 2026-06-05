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
from src.workers.shadowban_canary import ShadowbanCanary
from src.workers.upvote_booster_worker import UpvoteBoosterWorker

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

            # Shadowban canary: cheap (a few JSON fetches), runs every cycle so we
            # catch a shadowban quickly. If it fires a halt, subsequent workers
            # auto-skip via operation_blocked_result.
            try:
                canary_result = ShadowbanCanary().run_once()
                status = canary_result.get("status", "ok") if isinstance(canary_result, dict) else canary_result
                print(f"[loop] canary: {status}")
                if status == "halt_fired":
                    print(f"[loop] !!! HALT FIRED: {canary_result.get('reason')} — posting will pause until resolved with `python main.py resume-agent`")
            except Exception as exc:
                logger.exception("canary failed: %s", exc)
                print(f"[loop] canary failed: {exc}")

            # Upvote booster: checks recent comments for real human engagement,
            # then has the booster account add upvotes a few minutes later.
            # Silently skips if REDDIT_BOOSTER_USERNAME is not configured.
            try:
                booster_result = await UpvoteBoosterWorker().run_once()
                boosted = booster_result.get("boosted", 0) if isinstance(booster_result, dict) else 0
                reason = booster_result.get("reason", "") if isinstance(booster_result, dict) else ""
                if boosted:
                    print(f"[loop] booster: boosted {boosted} comment(s)")
                else:
                    print(f"[loop] booster: {reason or 'no eligible comments'}")
            except Exception as exc:
                logger.exception("booster failed: %s", exc)
                print(f"[loop] booster failed: {exc}")

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
