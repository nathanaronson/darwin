# Follow-up 1 — Tournament concurrency + referee observability

**Owner:** TBD  •  **Branch:** `followup/tournament-concurrency`

## Why

A run of gen 2 on Gemini 2.5 Flash produced 12 games, **all** with
`termination: "time"` after 0–1 moves. Baseline played a legal first move,
the generated engine played a (fallback) legal reply, then baseline timed
out on move 2. Root cause is the round-robin firing every pairing in
parallel — with 3 engines and `games_per_pairing=2`, that's 12 games ×
~12 LLM calls each happening concurrently. Under Gemini's rate limits
individual move calls balloon past the referee's 25s per-move timeout.

Result: the "tournament" is pure noise. The winner is whichever engine's
bugs happen to fire *after* the opposing engine's rate-limit-induced
timeout.

## What to do

### 1. Gate parallelism at the tournament level

`backend/darwin/tournament/runner.py` currently does one big
`asyncio.gather(*pairing_coros)`. Add a semaphore so at most
`settings.max_parallel_games` run at a time (default **2**, tunable in
`.env`). The tournament still takes the same wall-clock time on a fast
provider, but stops self-immolating on a slow one.

```python
# config.py
max_parallel_games: int = 2

# runner.py
sem = asyncio.Semaphore(settings.max_parallel_games)
async def _guarded(coro):
    async with sem:
        return await coro
results = await asyncio.gather(*[_guarded(c) for c in pairings])
```

### 2. Surface the real termination reason

`referee.py` already distinguishes `time`, `error`, `illegal_move`,
`checkmate`, `stalemate`, `max_moves`. Verify the `error` path carries
the exception repr into the log and the PGN comment so post-mortems are
possible.

- Log `log.warning("game error: %s vs %s: %r", white.name, black.name, exc)` in the `except Exception:` branch.
- Add the exception class name to the PGN as a comment header (`[ErrorClass "TypeError"]`) so the frontend can show it.

### 3. Optional — per-move time budget

Today `timeout_s = time_per_move_ms/1000 + 5`. That 5-second padding is a
magic number. Either justify it in a comment or make it configurable.

## Done when

- [ ] `settings.max_parallel_games` exists and defaults to 2.
- [ ] Running gen 2 on the Gemini provider produces at least one **real** game (≥ 10 moves, terminates on `checkmate`/`stalemate`/`max_moves`, not `time`).
- [ ] The `error` termination path logs the exception type + message.
- [ ] A new test in `backend/tests/test_runner.py` asserts the semaphore caps in-flight games.

## Files to touch

- `backend/darwin/config.py` (new setting)
- `backend/darwin/tournament/runner.py` (semaphore)
- `backend/darwin/tournament/referee.py` (error logging / PGN annotation)
- `backend/tests/test_runner.py` (new test)
- `.env.example` (document the new knob)

## Do **not** touch

- `backend/darwin/api/websocket.py` event shapes (frozen contract).
- The `Engine` Protocol in `engines/base.py` (frozen).
