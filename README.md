# PromptHunt Reddit Agent MVP

Compliance-first Reddit opportunity agent that discovers high-signal threads through a Kernel-backed browser, drafts one-product replies for approval, posts approved replies through an agent-controlled browser session, tracks outcomes, and updates an agent health score over time.

## What changed

- The original Playwright Reddit poster now lives in [`legacy/`](./legacy).
- The new runtime uses:
  - FastAPI for the operator/API surface
  - a shared Python domain package for scoring, lifecycle, and replay
  - LangGraph + Temporal-ready workflows for orchestration
  - Kernel + Browser Use for browser-based Reddit discovery and posting
  - a Next.js dashboard in [`apps/dashboard`](./apps/dashboard)
  - Docker Compose infra in [`infra/compose`](./infra/compose)

## Quick start

1. Copy `.env.example` to `.env` and fill in OpenAI, Kernel, browser-agent, and analytics credentials.
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

OpenAI-backed runtime defaults:

- `LLM_MODE=openai`
- `GENERATION_MODEL=gpt-5.4`
- `EVALUATOR_MODEL=gpt-5.4-mini`
- `OPENAI_API_KEY` is used for drafting, evaluation, and critic passes
- `BROWSER_AGENT_API_KEY` / `BROWSER_AGENT_BASE_URL` remain optional overrides for browser recovery and otherwise fall back to the OpenAI settings

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
