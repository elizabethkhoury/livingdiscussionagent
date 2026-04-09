# PromptHunt Reddit Agent MVP

Compliance-first Reddit opportunity agent that discovers high-signal threads, drafts one-product replies for approval, tracks outcomes, and updates an agent health score over time.

## What changed

- The original Playwright Reddit poster now lives in [`legacy/`](./legacy).
- The new runtime uses:
  - FastAPI for the operator/API surface
  - a shared Python domain package for scoring, lifecycle, and replay
  - LangGraph + Temporal-ready workflows for orchestration
  - a Next.js dashboard in [`apps/dashboard`](./apps/dashboard)
  - Docker Compose infra in [`infra/compose`](./infra/compose)

## Quick start

1. Copy `.env.example` to `.env` and fill in Reddit and analytics credentials.
2. Start local infra:

```bash
docker compose -f infra/compose/docker-compose.yml up -d
```

3. Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

4. Start the API:

```bash
uvicorn services.api.main:app --reload
```

5. Start the worker:

```bash
python -m services.worker.main
```

6. Start the dashboard:

```bash
cd apps/dashboard
bun install
bun run dev
```

## Checks

- Python format: `ruff format .`
- Python lint: `ruff check .`
- Python tests: `pytest`
- Dashboard lint: `cd apps/dashboard && bun run lint`
- Dashboard typecheck: `cd apps/dashboard && bun run typecheck`
