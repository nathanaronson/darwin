# Cubist

A self-improving chess engine that evolves its own scaffolding overnight via agentic tournament selection.

> Point72 Hackathon — 24-hour build.

## What it does

A fixed LLM plays chess inside a harness. Each generation:

1. A **strategist agent** asks 5 distinct questions about how the current champion could be improved.
2. **5 builder agents** work in parallel — each writes a modified engine answering one question.
3. The 5 candidates + the reigning champion play a round-robin tournament.
4. The top scorer becomes the new champion *only if* it beats the prior champion head-to-head.
5. Repeat.

Full design: see [`docs/proposal.pdf`](./docs/proposal.pdf).

## Repo layout

```
backend/      Python: engines, agents, tournament, API
frontend/     React + Vite dashboard
scripts/      One-off CLIs (run a generation, eval matches)
plans/        Per-person build plans for the 5-person team
docs/         Reference docs (proposal, architecture)
```

## Setup

**Backend:**
```bash
cd backend
uv sync
cp ../.env.example ../.env  # then fill in GEMINI_API_KEY
uv run uvicorn cubist.api.server:app --reload
```

For Gemini free tier, keep the model settings on `gemini-3-flash-preview`.
If you hit `429` rate limits, lower `LLM_MAX_CONCURRENCY` to `1`.

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Run a generation (CLI):**
```bash
cd backend
uv run python -m cubist.orchestration.run --generations 1
```

## Team

Five engineers working in parallel, each on their own branch. Plans live in [`plans/`](./plans/):

| Branch | Owner | Workstream |
|---|---|---|
| `feat/engine-core` | Person A | Engine Protocol, baseline, registry |
| `feat/tournament` | Person B | Referee, runner, Elo, selection gate |
| `feat/agents` | Person C | Strategist, builder, validator |
| `feat/frontend` | Person D | Dashboard, board, charts, strategist feed |
| `feat/infra` | Person E | API, WebSocket, DB, orchestration, demo |

## Frozen contracts (don't change without team sync)

- **Engine Protocol** — `backend/cubist/engines/base.py`
- **DB schema** — `backend/cubist/storage/models.py`
- **WebSocket events** — `backend/cubist/api/websocket.py` and `frontend/src/api/events.ts`
