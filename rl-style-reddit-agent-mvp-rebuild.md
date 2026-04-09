# RL-Style Reddit Agent MVP Rebuild

## Summary
- Replace the current single-file Playwright poster with a compliance-first system that discovers Reddit opportunities, drafts one-product replies, queues them for human approval, opens the target thread for manual posting, observes outcomes, and updates an agent point score over time.
- Keep Python for backend orchestration and scoring, add a TypeScript web dashboard for operator review, and use Docker Compose for local infra: PostgreSQL + pgvector, Redis, Temporal, and Metabase. Use PostHog Cloud for event analytics to avoid self-hosting overhead in the MVP.
- Treat the existing repo as legacy seed logic only. Preserve the current keyword lists and prompt heuristics as initial data, but do not keep the current plaintext-credential Playwright posting flow in the production path.

## Current-State Reset
- Move `bot.py`, `reply_generator.py`, `quality_scorer.py`, `semantic_filter.py`, and `thread_monitor.py` into a `legacy/` area and stop importing them from the new runtime.
- Remove `.env` secrets from tracked repo state and rotate the exposed Reddit and Mistral credentials before any implementation work continues.
- Replace browser-scraping discovery with official Reddit read-only API access for post/comment retrieval and polling. Manual posting remains outside the API path for MVP.

## Target Architecture
- `services/api`: FastAPI service for dashboard APIs, approvals, observations, replay, and agent health.
- `services/worker`: Python Temporal worker hosting LangGraph graphs for discovery, evaluation, draft generation, critic pass, memory updates, and daily reflection.
- `apps/dashboard`: Next.js + TypeScript operator UI, installed with `bun`, for queue review, replay, health state, and analytics.
- `infra/compose`: Docker Compose definitions for Postgres with pgvector, Redis, Temporal, and Metabase.
- `config/rules`: YAML subreddit profiles, product routing rules, safety thresholds, and lifecycle thresholds.
- `data/replays`: captured thread snapshots used for deterministic offline evaluation.

## Core Runtime Flow
1. Sense every 10 minutes per subreddit profile using Reddit API search/new endpoints and ingest posts plus top replyable comments.
2. Interpret each candidate with deterministic features first, then evaluator-model scoring for relevance, replyability, promo fit, risk, and uncertainty.
3. Decide `abstain`, `queue_draft`, or `watch_only` using a rules engine plus expected-value thresholding.
4. Act by generating one draft, running a critic pass, deduping against semantic history, and placing the draft in the approval queue.
5. After approval, open the exact Reddit thread and copy-ready reply in the dashboard for manual posting; log operator confirmation as the execution event.
6. Observe outcomes on a schedule at 1h, 24h, 72h, and 7d: score deltas, replies, moderator removals, link clicks, signup events, paid conversions, and account health.
7. Learn nightly by updating feature weights, subreddit priors, timing priors, product-routing confidence, and condensed memory summaries.
8. Reflect daily with an agent health summary and threshold checks that can pause or retire the policy version.

## Product Routing Rules
- Route to `prompthunt.me` only when the thread is about prompt discovery, storage, reuse, prompt quality, or finding proven prompts.
- Route to `upwordly.ai` only when the thread is about LinkedIn posting, thought-leadership writing, creator workflow, or repurposing expertise into posts.
- Mention exactly one product per draft.
- Abstain when neither product is a strong fit, even if the thread is high engagement.

## Memory and Lifecycle
- Working memory: recent candidate history, subreddit-specific behavior, unresolved operator feedback, and last 7 days of actions.
- Episodic memory: per-action snapshots with thread text, draft, rationale, approval outcome, and observed metrics.
- Semantic memory: distilled lessons stored in pgvector, grouped by subreddit, product, and failure/success pattern.
- Identity memory: stable voice constraints, taboo phrasing, disclosure style, and subreddit-specific tone notes.
- Health states: `seed` at launch, `mature` after 25 approved actions, `stressed` below 25 points, `dormant` after 7 days paused, `retired` below 0 points for 3 consecutive daily reflections.
- Retirement behavior: spawn a new policy version on the same Reddit account with inherited semantic/identity memory, cleared working memory, reset score to 50, and stricter initial thresholds for 7 days.

## Reward Function
- Base reward at 72h: `+20` paid conversion, `+8` qualified signup, `+3` positive substantive reply, `+1` net upvote above 2, `-4` negative reply, `-8` moderator removal/report, `-3` zero engagement after approval and posting, `-5` operator marks as awkward/spammy.
- Apply a depth multiplier from `0.6` to `1.5` from evaluator scoring on specificity, usefulness, honesty, and thread alignment; this prevents shallow upvote bait from dominating.
- Apply token penalty `-0.002` per total model token used for that action.
- Use paid conversion as the primary optimization target in experiments, but keep point updates dense enough for learning with sparse revenue signals.

## Safety and Compliance Rules
- Hard-block subreddits that ban self-promotion, bots, or external links unless the profile explicitly allows comment participation without links.
- Hard-block duplicate or near-duplicate drafts against the last 30 days of approved outputs using embedding similarity.
- Hard-block threads involving crisis, legal, medical, harassment, or explicit “no promotion” requests.
- Require model confidence above `0.72`, risk below `0.28`, and expected value above `1.5` to queue a draft.
- Store legible reasons for every abstain, queue, approval, rejection, and lifecycle transition.

## Public APIs / Interfaces
- `POST /ingest/reddit/sync`: trigger backfill or one-shot discovery for configured subreddits.
- `GET /candidates`: list scored candidates with features, risk, route choice, and abstain reasons.
- `POST /drafts/{candidate_id}/generate`: generate or regenerate a draft plus critic notes.
- `POST /approvals/{draft_id}`: approve or reject with operator feedback and optional edits.
- `POST /observations/reddit`: ingest engagement snapshots from polling jobs.
- `GET /agents/{agent_id}/health`: current state, score, thresholds, recent failures, and retirement risk.
- `GET /replays/{run_id}`: full decision trace for one candidate from sense through reward.
- Shared data contracts: Pydantic models in Python, OpenAPI-generated TS client for dashboard consumption.

## Data Model
- Tables: `reddit_candidates`, `candidate_features`, `drafts`, `approvals`, `actions`, `observations`, `agent_policies`, `agent_scores`, `memory_entries`, `subreddit_profiles`, `experiment_assignments`, `product_click_events`, `conversion_events`.
- Vector indexes on `memory_entries.embedding` and `drafts.embedding` for retrieval and repetition checks.
- Redis keys for short-lived candidate dedupe, rate windows, and pending observation polls.
- Temporal workflows: `discover_candidates`, `evaluate_candidate`, `generate_draft`, `observe_action`, `nightly_learning`, `daily_reflection`.

## MVP Dashboard
- Queue view with candidate context, route decision, draft, critic findings, and approve/reject/edit actions.
- Replay view showing features, scores, model prompts, and the exact reason a candidate was queued or skipped.
- Health page with current score, state, weekly outcomes, top failing subreddits, and kill switch.
- Analytics page for conversion funnel, outcome by subreddit, outcome by product, and token cost per approved draft.

## Testing and Acceptance
- Unit tests for product routing, rules-engine blocks, lifecycle transitions, reward computation, token penalty, and memory compaction.
- Integration tests for `candidate -> draft -> approval -> manual handoff -> observation -> score update`.
- Replay tests over a fixed dataset of Reddit threads to verify abstain rate, routing precision, and safety blocks before live use.
- Contract tests for FastAPI OpenAPI schema and generated TS client.
- Acceptance criteria: operator can review a ranked queue, approve a draft, manually post it, see outcomes update automatically, and inspect why the agent changed score or state.

## Assumptions and Defaults
- MVP uses a web dashboard, not CLI, for approvals and replay.
- Posting remains manual after approval; no autonomous posting in MVP.
- Main draft model defaults to `Opus 4.6`; evaluator/critic/reward model defaults to `GPT-5.4-mini`; both are wrapped behind provider interfaces for later swap.
- Dashboard is Next.js + TypeScript with `bun`; backend remains Python because LangGraph and Temporal are core requirements.
- Local development uses Docker Compose because `docker` and `bun` are available, while local `psql`, `redis-server`, and `temporal` CLIs are not.
- Existing scripts are treated as disposable prototype code, not migration targets, except for reusing keyword/topic seeds where still useful.
