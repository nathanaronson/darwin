# Build Plans

Each engineer takes one plan and one branch. Read your own plan in full, then skim the other four so you know who you depend on and who depends on you.

| Plan | Branch | Owner |
|---|---|---|
| [Engine core & baseline](./person-a-engine-core.md) | `feat/engine-core` | A |
| [Tournament & referee](./person-b-tournament.md) | `feat/tournament` | B |
| [Agents (strategist + builder)](./person-c-agents.md) | `feat/agents` | C |
| [Frontend dashboard](./person-d-frontend.md) | `feat/frontend` | D |
| [Infra, API, orchestration, demo](./person-e-infra.md) | `feat/infra` | E |

## Frozen contracts

These three files define how the workstreams integrate. **Do not change them without paging the team.**

- `backend/darwin/engines/base.py` — Engine Protocol
- `backend/darwin/storage/models.py` — SQLite schema
- `backend/darwin/api/websocket.py` + `frontend/src/api/events.ts` — WS event payloads

## Merge order

1. Person A merges `feat/engine-core`. Unblocks B and C.
2. Person B merges `feat/tournament`. Unblocks E's full orchestration.
3. Person C merges `feat/agents`. Unblocks E's real generation runs.
4. Person E merges `feat/infra`. Unblocks D's switch from mocks to live.
5. Person D merges `feat/frontend`. Demo-ready.

After D merges: eval, polish, demo rehearsal.
