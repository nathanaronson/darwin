# Tournament Operations

The tournament runner schedules a round robin over every ordered engine pair.
Each ordered pair runs `games_per_pairing` games, so four engines with one game
per pairing produce `4 * 3 = 12` games.

## Concurrency Limit

`round_robin` caps concurrent games with `settings.max_parallel_games`, which
defaults to `2` and can be overridden with:

```env
MAX_PARALLEL_GAMES=2
```

This limit exists because LLM-backed engines can share one provider rate limit.
Launching every game at once can make all move calls slow down together and
turn the tournament into timeout noise. A small game-level limit preserves
parallelism while keeping provider pressure bounded.

Set `MAX_PARALLEL_GAMES=1` for the most conservative replay/debug run. Increase
it only after the active provider can complete real games without systematic
`time` terminations.

## Referee Observability

The referee adjudicates engine exceptions as `termination == "error"`. It logs
the exception with engine names and writes the exception class into the PGN:

```pgn
[ErrorClass "TypeError"]
```

The WebSocket event shape is unchanged. Consumers can read the PGN header for
post-mortem display without changing the frozen event contract.

The per-move timeout is still `time_per_move_ms / 1000 + 5`. The five-second
pad is deliberate: it absorbs provider/network jitter beyond the requested
engine budget, while still bounding a stalled move.
