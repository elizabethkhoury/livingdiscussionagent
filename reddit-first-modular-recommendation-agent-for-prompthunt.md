# Reddit-First Modular Recommendation Agent for PromptHunt

## Summary
Replace the current single-loop Reddit bot with a modular Python system that separates policy, reasoning, generation, execution, review, and learning. The first version stays Reddit-first, keeps Playwright as the posting transport, uses Postgres for durable state, adds a local web dashboard for review, and allows hybrid autonomy:
- purely informational replies may autopost
- any monetized or referral-style product mention must route to human review
- all behavior is governed by explicit policy rules, not prompt-only instructions

This plan also removes the current deceptive behavior. The new system must never pretend to be an unaffiliated “real Reddit user,” must never fabricate personal experience, and must never force a product mention when the thread is better served without one.

## Scope
In scope:
- Reddit ingestion, candidate scoring, classification, decisioning, drafting, review, posting, monitoring, learning
- PromptHunt-specific rules as a configuration layer on top of a reusable core
- Local web dashboard for draft approval, queue inspection, and outcome review
- Postgres-backed feedback and experiment storage
- Bounded auto-tuning for low-risk thresholds and strategy weights

Out of scope for v1:
- Multi-platform support beyond internal abstractions
- Full reinforcement-learning or end-to-end autonomous policy rewriting
- Any stealth-growth tactics, persona deception, or undisclosed affiliate routing
- Rich frontend polish beyond a functional local moderation dashboard

## Current-State Replacement
The current repo has four behaviors that should be explicitly replaced:
- `reply_generator.py` currently instructs the model to sound like a normal user and disguise product mentions. Replace with policy-safe drafting rules.
- `quality_scorer.py` currently self-scores only for “looks natural / not spammy.” Replace with multi-axis evaluation.
- `semantic_filter.py` currently does only topic relevance. Replace with structured classification.
- `thread_monitor.py` currently stores only replied IDs. Replace with durable outcome tracking in Postgres.

`bot.py` should stop containing business logic. It becomes orchestration only.

## Target Project Structure
Use Python and reorganize into a package-based layout:

```text
src/
  app/
    config.py
    logging.py
    settings.py
  domain/
    enums.py
    models.py
    policies.py
  ingest/
    reddit_reader.py
    subreddit_rules.py
    candidate_selector.py
  classify/
    relevance.py
    intent.py
    commercial_fit.py
    policy_risk.py
    value_add.py
  decide/
    engine.py
    strategy_selector.py
  generate/
    draft_writer.py
    evaluators.py
    disclosures.py
  review/
    api.py
    templates/
    service.py
  execute/
    playwright_transport.py
    poster.py
  monitor/
    engagement_fetcher.py
    moderation_signals.py
  learn/
    feature_builder.py
    trainer.py
    bounded_tuning.py
  storage/
    db.py
    schema.py
    repositories.py
    migrations/
  workers/
    ingest_worker.py
    review_worker.py
    monitor_worker.py
    learning_worker.py
tests/
main.py
```

## Chosen Implementation Stack
- Python 3.12
- FastAPI for local dashboard and internal admin API
- Jinja2 + HTMX for the local dashboard
- SQLAlchemy 2.x + Alembic + `psycopg` for Postgres access
- Pydantic Settings for configuration
- Playwright retained as the only posting transport in v1
- Sentence-transformers may remain for semantic relevance, but must be wrapped behind a classifier interface
- LLM provider wrapped behind a single `LLMClient` abstraction so Mistral can be swapped later

## Core Domain Types and Interfaces
These are the public internal interfaces the implementation should standardize on.

### Domain models
Use Pydantic models or dataclasses for these types:
- `RedditPostCandidate`
- `RedditCommentCandidate`
- `ThreadContext`
- `ClassificationResult`
- `DecisionResult`
- `DraftReply`
- `ReviewItem`
- `PostAttempt`
- `EngagementSnapshot`
- `LearningExample`
- `StrategyWeights`
- `PolicyDecisionTrace`

### Key enums
- `IntentType = question | complaint | comparison | recommendation_request | discussion | showcase | news | job_posting | other`
- `DecisionAction = skip | autopost_info | queue_review_product | queue_review_risky | queue_review_low_confidence`
- `ResponseStrategy = educational | comparative | experiential | resource_linking`
- `PromotionMode = none | plain_mention | disclosed_monetized`
- `RiskLevel = low | medium | high | block`

### Service interfaces
Define these protocols or abstract base classes:
- `CandidateSource.fetch_candidates() -> list[ThreadContext]`
- `Classifier.classify(thread: ThreadContext) -> ClassificationResult`
- `DecisionEngine.decide(thread: ThreadContext, classification: ClassificationResult) -> DecisionResult`
- `DraftWriter.compose(thread: ThreadContext, decision: DecisionResult) -> DraftReply | None`
- `DraftEvaluator.evaluate(thread: ThreadContext, draft: DraftReply) -> DraftEvaluation`
- `ReviewService.enqueue(draft: DraftReply, reason: str) -> ReviewItem`
- `PostingTransport.publish(review_or_draft_id: str) -> PostAttempt`
- `OutcomeMonitor.refresh(post_attempt_id: str) -> EngagementSnapshot`
- `LearningService.update() -> LearningUpdateReport`

## Classification Contract
`ClassificationResult` must include:
- `intent`
- `relevance_score: float`
- `commercial_opportunity: low | medium | high`
- `value_add_score: float`
- `policy_risk_score: float`
- `promo_fit_score: float`
- `tone: beginner | intermediate | advanced | frustrated | skeptical | neutral`
- `subreddit_promo_policy: allow | review_only | deny`
- `duplicate_similarity_score: float`
- `reason_codes: list[str]`

### Default classifier rules
Use these v1 defaults:
- `relevance_score < 0.65` -> skip
- `value_add_score < 0.70` -> skip
- `duplicate_similarity_score > 0.92` against any posted draft in the last 14 days -> skip
- `intent == discussion` and `value_add_score < 0.80` -> skip
- `subreddit_promo_policy == deny` -> no product mention allowed
- `policy_risk_score >= 0.55` -> review only
- `promo_fit_score >= 0.75` and `commercial_opportunity == high` -> product mention eligible
- `promo_fit_score < 0.75` -> informational only, even if the thread is commercial in nature

## Decision Engine Policy
The decision engine must be rule-first, not LLM-first.

### Hard blocks
Immediately skip when any of these are true:
- thread is a meme, job listing, obvious self-promo thread, or breaking-news thread with no actionable help needed
- subreddit or thread rules forbid self-promotion or affiliate mentions
- the agent cannot add non-obvious value
- the only way to mention PromptHunt would require pretending to have used it or hiding affiliation
- the thread is too old, locked, removed, or has hostile moderation context
- the account has posted in the same thread already

### Autopost informational
Autopost is allowed only when all of these are true:
- `DecisionAction == autopost_info`
- `PromotionMode == none`
- `policy_risk_score < 0.35`
- `DraftEvaluation.overall_score >= 0.80`
- `DraftEvaluation.authenticity_score >= 0.85`
- `DraftEvaluation.specificity_score >= 0.75`
- no disclosure is required because no monetized mention is present

### Human review required
Send to dashboard review when any of these are true:
- `PromotionMode == disclosed_monetized`
- `policy_risk_score >= 0.35`
- `DraftEvaluation.overall_score < 0.80`
- confidence disagreement between classifiers exceeds a fixed threshold
- subreddit is marked `review_only`
- thread is high-visibility or moderator-sensitive

## PromptHunt-Specific Policy Layer
Implement PromptHunt-specific configuration as data, not hard-coded prose.

### PromptHunt mention eligibility
A PromptHunt mention is eligible only when at least one is true:
- user explicitly asks where to save, organize, find, or reuse prompts
- user describes repeated loss, rewriting, or fragmentation of prompts
- user asks for prompt libraries, repositories, shared prompts, or discovery tools
- user is comparing prompt-management workflows

A PromptHunt mention is not eligible when:
- thread is about general AI news, company drama, pricing, hiring, or memes
- thread is about prompting in a way where product mention adds no clear value
- product mention would shift the answer from useful to salesy

### Disclosure rule chosen for v1
Because you selected “disclose monetized cases,” use this exact rule:
- `disclosed_monetized` is required when the reply includes a tracked link, affiliate code, referral code, coupon, UTM meant for attribution, or any compensation-based referral mechanism
- `plain_mention` is allowed only when there is no tracked referral and no monetized incentive
- even for `plain_mention`, the draft must not claim personal use unless the operator explicitly approved a truthful first-person stance in config

### Allowed phrasing policy
Allowed:
- neutral, factual, optional mention after solving the problem
- no urgency, no CTA-heavy verbs, no superlatives

Blocked:
- “I use this every day” unless operator-approved and true
- “someone mentioned this to me” if fabricated
- “best,” “amazing,” “must-have,” or comparative hype
- any wording designed to conceal affiliation in monetized cases

## Draft Composition Contract
Every reply draft must follow this structure:
1. Acknowledge the actual problem or context
2. Give one concrete, thread-specific piece of useful help
3. Optionally mention a category or product only if the decision engine allowed it
4. Keep the tone aligned to the thread and avoid CTA-heavy copy

### Draft fields
`DraftReply` must include:
- `body`
- `strategy`
- `promotion_mode`
- `contains_link`
- `disclosure_text`
- `decision_trace_id`
- `thread_id`
- `autopost_eligible: bool`

### Draft evaluator dimensions
Replace the current 1-to-5 self-score with:
- `authenticity_score`
- `specificity_score`
- `helpfulness_score`
- `promo_pressure_score`
- `policy_compliance_score`
- `overall_score`
- `fail_reasons`

Autopost rejects on:
- `promo_pressure_score > 0.20`
- `policy_compliance_score < 0.90`
- any fail reason in `deception`, `generic_reply`, `insufficient_value`, `undisclosed_monetization`

## Review Dashboard
Build a local FastAPI dashboard with these pages:
- `GET /reviews`
- `GET /reviews/{id}`
- `POST /reviews/{id}/approve`
- `POST /reviews/{id}/reject`
- `POST /reviews/{id}/edit-and-approve`
- `GET /attempts`
- `GET /threads/{reddit_thread_id}`
- `GET /learning`
- `GET /settings`

Dashboard capabilities:
- inspect thread context, classifier outputs, and draft body
- see why the item was routed to review
- edit draft text before posting
- see whether disclosure was triggered and why
- inspect moderation and engagement outcomes
- pause or resume autopost mode globally

## Postgres Schema
Create these tables:

### `threads`
- `id`
- `platform_thread_id`
- `platform`
- `subreddit`
- `title`
- `body`
- `url`
- `author`
- `created_at_platform`
- `ingested_at`

### `thread_comments`
- `id`
- `platform_comment_id`
- `thread_id`
- `author`
- `body`
- `created_at_platform`

### `classifications`
- `id`
- `thread_id`
- `target_comment_id`
- `intent`
- `relevance_score`
- `commercial_opportunity`
- `value_add_score`
- `policy_risk_score`
- `promo_fit_score`
- `tone`
- `subreddit_promo_policy`
- `duplicate_similarity_score`
- `reason_codes_json`
- `created_at`

### `decisions`
- `id`
- `classification_id`
- `action`
- `promotion_mode`
- `requires_review`
- `trace_json`
- `created_at`

### `drafts`
- `id`
- `decision_id`
- `body`
- `strategy`
- `contains_link`
- `disclosure_text`
- `autopost_eligible`
- `evaluation_json`
- `status`
- `created_at`

### `reviews`
- `id`
- `draft_id`
- `status`
- `review_reason`
- `reviewer_note`
- `reviewed_at`

### `post_attempts`
- `id`
- `draft_id`
- `transport`
- `status`
- `posted_comment_id`
- `error_message`
- `created_at`
- `posted_at`

### `engagement_snapshots`
- `id`
- `post_attempt_id`
- `score`
- `reply_count`
- `is_deleted`
- `is_removed`
- `is_locked`
- `captured_at`

### `learning_examples`
- `id`
- `thread_id`
- `draft_id`
- `features_json`
- `outcome_label`
- `reward_score`
- `created_at`

### `strategy_weights`
- `id`
- `strategy`
- `weight`
- `version`
- `updated_at`

### `system_events`
- `id`
- `event_type`
- `payload_json`
- `created_at`

## Worker Flows
Implement four processes.

### Ingest worker
- pull new posts from configured subreddits every 5 minutes
- fetch top-level comments for candidate reply opportunities
- load subreddit-specific rules cache
- create `ThreadContext`
- run classification and decision
- create draft or skip record

### Review worker
- if decision is `autopost_info`, publish directly after final evaluator pass
- if decision requires review, create dashboard item and stop
- after operator approval, send to posting transport

### Monitor worker
- poll posted comments on a fixed schedule
- record score, replies, removal, deletion, lock state
- label obvious negative outcomes for learning

### Learning worker
- run every 24 hours
- compute reward scores from engagement and negative moderation signals
- update bounded strategy weights and low-risk thresholds only
- never change hard policy rules automatically

## Playwright Transport
Keep Playwright, but isolate it behind `PlaywrightPostingTransport`.

Rules:
- transport contains only browser/login/posting mechanics
- no business logic inside transport
- no draft generation, scoring, or decisioning inside transport
- transport accepts final approved text only

Add these safeguards:
- global per-hour cap
- subreddit-specific cooldown
- per-thread dedupe lock
- per-account daily cap
- circuit breaker when removals or rate-limit events spike
- screenshot + DOM snapshot on every failed publish attempt

Default execution caps:
- `max_autoposts_per_hour = 2`
- `max_total_posts_per_day = 12`
- `cooldown_between_threads_minutes = 25`
- `subreddit_daily_cap = 2`
- trip circuit breaker if `moderator_removals >= 2` in 24h or `rate_limits >= 3` in 12h

## Learning and Reward Function
Use the trust-weighted reward you described, but operationalize it as:

```text
reward =
  (0.35 * normalized_upvotes) +
  (0.25 * normalized_reply_depth) +
  (0.20 * survived_48h) +
  (0.20 * positive_followup_signal) -
  (0.60 * removal_flag) -
  (0.50 * deletion_flag) -
  (0.40 * strong_negative_reply_signal)
```

### Auto-tuned parameters allowed
Only these may be auto-tuned:
- strategy weights
- relevance threshold within `0.60..0.72`
- value-add threshold within `0.65..0.80`
- autopost evaluator threshold within `0.78..0.86`

### Parameters that must never auto-tune
- disclosure requirements
- hard block rules
- rate limits
- review-routing rules for monetized mentions
- banned subreddits or policy deny lists

### Tuning guardrails
- require at least 30 new examples before changing any threshold
- limit any threshold change to `0.02` per daily learning run
- freeze all tuning if any moderator removal occurred in the last 24 hours
- roll back the last tuning version if 7-day negative-signal rate worsens by more than 20%

## Configuration Surface
Introduce a real settings layer.

### Required settings
- Reddit credentials
- Postgres DSN
- LLM provider key
- enabled subreddits
- subreddit policy overrides
- operator disclosure preferences
- autopost enabled flag
- dashboard auth secret for local use
- global rate-limit settings

### PromptHunt config
Store these as settings:
- `product_name`
- `product_domain`
- `monetized_link_domains`
- `plain_mention_allowed`
- `first_person_claims_allowed`
- `default_disclosure_template`

Default disclosure template for monetized cases:
- `Disclosure: I’m affiliated with PromptHunt.`

## Testing and Acceptance Criteria
Create tests for the following scenarios.

### Policy tests
- recommendation thread with clear prompt-library fit and tracked link -> queue for review with disclosure required
- recommendation thread with clear fit and plain untracked mention -> allowed only if no monetization flag is present
- discussion thread with no unique value-add -> skip
- thread in a promo-deny subreddit -> informational only or skip, never product mention
- draft containing fabricated personal usage -> blocked

### Decision tests
- low relevance -> skip
- high relevance + high value-add + no promo fit -> autopost informational
- high relevance + high promo fit + monetized link -> review queue
- high risk + info-only draft -> review queue, not autopost

### Generator tests
- draft includes acknowledgment and concrete advice
- draft does not exceed length target
- draft avoids banned hype phrases
- monetized draft includes disclosure text
- informational autopost draft contains no disclosure if no monetization exists

### Storage tests
- thread, classification, decision, draft, review, attempt, and outcome rows are created in the right order
- dedupe rules prevent double-posting in the same thread
- learning examples are created only after monitoring data exists

### Transport tests
- Playwright publish success path
- rate-limit detection triggers backoff
- transport failure stores screenshot metadata and error state
- circuit breaker prevents additional publishes after negative-signal threshold

### Learning tests
- bounded thresholds do not move outside allowed ranges
- any removal freezes tuning
- rollback restores previous strategy version on degraded 7-day negative rate

### End-to-end acceptance
A successful v1 is one where:
- informational replies can be autoposted without review
- monetized mentions never autopost
- every post has a decision trace
- no product mention is generated unless the decision engine explicitly allowed it
- the operator can review, edit, approve, and inspect outcomes from the local dashboard
- strategy weights and low-risk thresholds adapt without changing policy rules

## Migration Plan
Implement in this order:
1. Add package structure, settings, Postgres connection, and Alembic.
2. Move current logic out of `bot.py` into typed services.
3. Replace `replied_posts.json` with database-backed dedupe and attempt tracking.
4. Add structured classifiers and decision engine.
5. Replace the current generator prompt with policy-safe drafting plus evaluator passes.
6. Add FastAPI dashboard and review queue.
7. Wrap existing Playwright posting logic behind `PlaywrightPostingTransport`.
8. Add monitoring and engagement snapshots.
9. Add bounded learning worker and strategy-weight updates.
10. Remove or archive legacy deceptive prompts and single-score logic.

## Assumptions and Defaults
- The repo remains Python-first.
- Playwright stays as the primary posting transport in v1 because that was explicitly selected.
- Read-side ingestion can continue using Reddit thread JSON endpoints initially, while posting remains Playwright-based.
- “Monetized case” means any tracked or compensated referral, not a plain untracked text mention.
- Local dashboard is for an operator on a trusted machine, not a public multi-user admin app.
- Postgres is available for local or hosted development.
- The system is optimized for long-term trust-weighted engagement, not click maximization.
