# PromptHunt Reddit Agent

Reddit-first recommendation agent for PromptHunt. It ingests threads from configured subreddits, classifies and scores opportunities, drafts replies, queues reviews, and can post approved replies through a Playwright-driven Reddit session.

## What This Repo Contains

- `main.py`: CLI entrypoint for bootstrap, dashboard, and one-shot workers
- `src/workers/ingest_worker.py`: pulls Reddit threads, classifies them, and creates drafts/reviews
- `src/workers/review_worker.py`: auto-posts approved or high-confidence drafts
- `src/workers/monitor_worker.py`: refreshes post outcomes and writes learning examples
- `src/workers/learning_worker.py`: updates learned weights from stored outcomes
- `src/review/`: FastAPI review dashboard
- `src/storage/`: SQLAlchemy models and database access

## Prerequisites

- Python `3.12+`
- PostgreSQL
- Chromium dependencies needed by Playwright
- A Reddit account if you want to post through the Playwright transport
- A Mistral API key if you want real LLM generations instead of the heuristic fallback

## Local Setup

### 1. Create a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
python -m playwright install chromium
```

### 3. Create the database

This project defaults to:

```text
postgresql+psycopg://localhost/prompthunt
```

Create that database, or point `POSTGRES_DSN` at a different one:

```bash
createdb prompthunt
```

### 4. Create `.env`

The app loads settings from `.env`. A good local starting point is:

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000

POSTGRES_DSN=postgresql+psycopg://localhost/prompthunt

LLM_PROVIDER=mistral
MISTRAL_API_KEY=your-mistral-api-key

REDDIT_USERNAME=your-reddit-username
REDDIT_PASSWORD=your-reddit-password

CHROME_PROFILE_DIR=chrome_profile

AUTOPOST_ENABLED=false
```

Notes:

- If `MISTRAL_API_KEY` is missing, the app falls back to a heuristic LLM client.
- Reddit credentials are only required for Playwright posting.
- `AUTOPOST_ENABLED=false` is a safer default for local setup while you validate the pipeline.

### 5. Bootstrap the schema

```bash
python main.py bootstrap
```

This uses `Base.metadata.create_all(...)` to create tables directly. Alembic is present in the repo, but migrations are not populated yet.

## Running the Project

### Review dashboard

```bash
python main.py dashboard
```

Then open:

```text
http://127.0.0.1:8000/reviews
```

Useful dashboard routes:

- `/reviews`
- `/attempts`
- `/learning`
- `/settings`

### One-shot worker commands

Run these manually while setting up or debugging:

```bash
python main.py ingest-once
python main.py review-once
python main.py monitor-once
python main.py learn-once
```

What they do:

- `ingest-once`: reads configured subreddits, classifies threads, creates decisions and drafts
- `review-once`: auto-posts eligible drafts or approved drafts
- `monitor-once`: refreshes engagement signals for posting attempts
- `learn-once`: updates learned strategy weights from stored outcomes

## Recommended First Local Run

Use this sequence for a safe smoke test:

```bash
python main.py bootstrap
python main.py ingest-once
python main.py dashboard
```

After that:

1. Open `/reviews` and inspect queued drafts.
2. Approve or reject a review in the dashboard.
3. Only run `python main.py review-once` after you are comfortable with your `.env` settings and Reddit account setup.

## Configuration Reference

These are the main settings defined in `src/app/settings.py`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Runtime environment label |
| `APP_HOST` | `127.0.0.1` | Dashboard bind host |
| `APP_PORT` | `8000` | Dashboard bind port |
| `POSTGRES_DSN` | `postgresql+psycopg://localhost/prompthunt` | SQLAlchemy connection string |
| `LLM_PROVIDER` | `mistral` | LLM backend selector |
| `MISTRAL_API_KEY` | unset | Required for live Mistral API calls |
| `REDDIT_USERNAME` | unset | Reddit login for Playwright posting |
| `REDDIT_PASSWORD` | unset | Reddit login for Playwright posting |
| `CHROME_PROFILE_DIR` | `chrome_profile` | Persistent browser profile path |
| `AUTOPOST_ENABLED` | `true` | High-level autopost toggle |
| `ENABLED_SUBREDDITS` | built-in list | Subreddits scanned during ingest |

There are additional thresholds and circuit-breaker settings in `src/app/settings.py` for rate limiting, daily caps, and scoring thresholds.

## Testing and Checks

Run the existing checks after changes:

```bash
ruff check .
pytest
```

## Troubleshooting

### `python main.py bootstrap` fails to connect to Postgres

Verify PostgreSQL is running and that `POSTGRES_DSN` points to an existing database.

### `review-once` fails before posting

Check:

- `REDDIT_USERNAME`
- `REDDIT_PASSWORD`
- Playwright Chromium installation
- Whether the local Chrome profile directory is writable

### LLM output looks too literal or weak

That usually means the code is using the heuristic fallback because `MISTRAL_API_KEY` is missing or invalid.

### Reddit posting is risky in local development

Keep `AUTOPOST_ENABLED=false`, use the dashboard to inspect drafts first, and only test posting with a controlled Reddit account.
