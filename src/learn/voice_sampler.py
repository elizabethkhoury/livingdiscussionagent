"""Scrapes real, well-upvoted Reddit comments and stores them as voice examples.

Every learning cycle this runs and:
  1. Pulls recent hot threads from our target subreddits
  2. Extracts short, well-upvoted comments (8-60 words, 5+ upvotes)
  3. Filters out bots, links, bullet lists, and any AI-tell phrases
  4. Stores up to 400 examples in a rotating JSON cache

Those examples get injected into the draft and conversation prompts so the
LLM sees how real people in those communities actually write — not our
hardcoded static examples. Fresh real writing beats anything we could hand-craft.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from src.app.settings import get_settings

logger = logging.getLogger(__name__)

CACHE_PATH = Path("data/voice_samples.json")
MAX_SAMPLES = 400
MIN_UPVOTES = 5
MIN_WORDS = 8
MAX_WORDS = 60

# Scrape at most this many subreddits per update to avoid rate-limiting
MAX_SUBREDDITS_PER_RUN = 8
POSTS_PER_SUB = 3
COMMENTS_PER_POST = 15

# Public-viewer UA — same approach as the shadowban canary
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"

# These patterns suggest structure / AI writing — skip that comment
_BOT_PATTERNS = [
    re.compile(r"\n[-*]\s"),          # bullet list
    re.compile(r"\n\n"),              # multi-paragraph
    re.compile(r"https?://"),         # links
    re.compile(r"^\s*\d+[.)]\s", re.MULTILINE),  # numbered list
    re.compile(r"\bedit\b", re.IGNORECASE),       # edited posts often have context missing
]

# AI-tell phrases — if a scraped comment has these it's probably AI itself
_AI_TELLS = [
    "furthermore", "moreover", "invaluable", "leverage", "utilize",
    "streamline", "holistic", "pivotal", "paramount", "transformative",
    "it's worth noting", "in essence", "at the end of the day",
    "i hope this helps", "feel free to", "let me know if",
    "keep up the", "great question", "absolutely,", "certainly,",
    "undeniably", "noteworthy", "delve into", "dive deep",
    "real conversations often", "natural flow", "authentic voice",
    "overall direction", "refining features", "usability insights",
    "in meaningful ways", "product development in",
]


class VoiceSampler:
    """Scrapes and caches real Reddit comments for use as prompt voice examples."""

    def __init__(self):
        self.settings = get_settings()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self) -> int:
        """Scrape fresh comments and add to cache. Returns number of new samples added."""
        subreddits = self.settings.enabled_subreddits[:MAX_SUBREDDITS_PER_RUN]
        new_samples: list[dict] = []

        for subreddit in subreddits:
            try:
                posts = self._fetch_hot_posts(subreddit, limit=POSTS_PER_SUB)
                for post in posts:
                    comments = self._fetch_top_comments(subreddit, post["id"])
                    for c in comments:
                        if self._is_good_sample(c):
                            new_samples.append({
                                "text": c["body"].strip(),
                                "subreddit": subreddit,
                                "upvotes": c.get("score", 0),
                                "scraped_at": datetime.utcnow().isoformat(),
                            })
                    time.sleep(2.0)  # be polite, same pacing as the canary
            except Exception as exc:
                logger.warning("voice_sampler fetch error subreddit=%s err=%s", subreddit, exc)
                continue

        if not new_samples:
            logger.info("voice_sampler: no new samples this run")
            return 0

        existing = self._load()
        combined = new_samples + existing  # new ones first
        # Deduplicate by text
        seen: set[str] = set()
        deduped = []
        for s in combined:
            key = s["text"][:120]
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        deduped = deduped[:MAX_SAMPLES]
        self._save(deduped)
        logger.info("voice_sampler added=%d total=%d", len(new_samples), len(deduped))
        return len(new_samples)

    def sample(self, n: int = 6, subreddit: str | None = None) -> list[str]:
        """Return n random real-comment examples. Prefers same subreddit if given."""
        examples = self._load()
        if not examples:
            return []

        if subreddit:
            sub = [e for e in examples if e.get("subreddit") == subreddit]
            other = [e for e in examples if e.get("subreddit") != subreddit]
            # Take up to half from same subreddit, fill rest from pool
            take_sub = min(len(sub), max(1, n // 2))
            pool = random.sample(sub, take_sub) + other
        else:
            pool = examples

        chosen = random.sample(pool, min(n, len(pool)))
        return [e["text"] for e in chosen]

    def count(self) -> int:
        return len(self._load())

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _fetch_hot_posts(self, subreddit: str, limit: int = 3) -> list[dict]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        try:
            data = self._fetch_json(url)
            children = data.get("data", {}).get("children", [])
            return [
                {"id": c["data"]["id"], "title": c["data"].get("title", "")}
                for c in children
                if c.get("kind") == "t3" and not c["data"].get("is_self") is False
            ]
        except Exception as exc:
            logger.debug("fetch_hot_posts error sub=%s err=%s", subreddit, exc)
            return []

    def _fetch_top_comments(self, subreddit: str, thread_id: str) -> list[dict]:
        url = f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}.json?limit={COMMENTS_PER_POST}&sort=top"
        try:
            data = self._fetch_json(url)
            children = data[1]["data"]["children"]
            return [
                {
                    "body": c["data"].get("body", ""),
                    "score": c["data"].get("score", 0),
                    "author": c["data"].get("author", ""),
                }
                for c in children
                if c.get("kind") == "t1"
            ]
        except Exception as exc:
            logger.debug("fetch_top_comments error thread=%s err=%s", thread_id, exc)
            return []

    def _fetch_json(self, url: str):
        req = urllib_request.Request(url, headers={"User-Agent": _UA})
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _is_good_sample(self, comment: dict) -> bool:
        body = (comment.get("body") or "").strip()
        if not body or body in ("[deleted]", "[removed]", "[ Removed by Reddit ]"):
            return False

        words = body.split()
        if len(words) < MIN_WORDS or len(words) > MAX_WORDS:
            return False

        if comment.get("score", 0) < MIN_UPVOTES:
            return False

        author = (comment.get("author") or "").lower()
        if author in ("automoderator", "[deleted]", "") or author.endswith("bot"):
            return False

        # Skip structured / bot-looking comments
        for pattern in _BOT_PATTERNS:
            if pattern.search(body):
                return False

        # Skip comments with AI tells
        body_lower = body.lower()
        if any(phrase in body_lower for phrase in _AI_TELLS):
            return False

        # Skip anything that looks like self-promotion
        if "http" in body_lower or "www." in body_lower:
            return False

        return True

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        if not CACHE_PATH.exists():
            return []
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, samples: list[dict]) -> None:
        CACHE_PATH.write_text(json.dumps(samples, indent=2), encoding="utf-8")
