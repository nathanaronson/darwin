# Cubist

A self-improving chess engine that evolves its own scaffolding overnight via agentic tournament selection.

> Point72 Hackathon — 24-hour build.

## What it does

A fixed LLM plays chess inside a harness. Each generation:

1. A **strategist agent** asks 2 distinct questions about how the current champion could be improved.
2. **2 builder agents** work in parallel — each writes a modified engine answering one question.
3. The 2 candidates + the reigning champion play a round-robin tournament.
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

The repo ships a `Makefile` with all the common targets — run `make help` to list them.

**First-time setup:**
```bash
make install              # uv sync backend + npm install frontend
cp .env.example .env      # then fill in ANTHROPIC_API_KEY (or GOOGLE_API_KEY, see below)
uv tool install honcho    # only if you plan to use `make dev` (runs both services together)
make seed                 # initialize the DB and insert baseline-v0 (idempotent)
```

**LLM provider:** set `LLM_PROVIDER=claude` (default) or `LLM_PROVIDER=gemini` in `.env`.
Claude uses `ANTHROPIC_API_KEY`; Gemini uses `GOOGLE_API_KEY`. When switching, also flip
the `*_MODEL` IDs to values your provider supports (e.g. `gemini-2.5-pro`). The strategist
and builder agents use function-calling on both providers; the call sites are unchanged.

**Running:**
```bash
make dev                  # backend (:8000) + frontend (:5173) together via honcho
# or run them separately in two terminals:
make backend
make frontend
```

**Trigger a generation:**
```bash
# via the API (backend must be running):
curl -X POST http://localhost:8000/api/generations/run

# or from the CLI:
make run                  # one generation
make run N=3              # three back-to-back
```

**Other useful targets:**
```bash
make test                 # pytest
make check                # lint + tests (pre-PR gate)
make smoke                # quick 10-move baseline self-play
make eval WHITE=baseline-v0 BLACK=random N=10   # head-to-head match
make replay               # re-emit persisted generations over WS (demo safety net)
make reset                # drop the DB and re-seed
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
