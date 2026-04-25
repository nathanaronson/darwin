# Changelog

What we built beyond the original 24-hour scope.

- **Two LLM providers behind one interface** — strategist/builder/player agents all go through `darwin.llm.complete*`, which dispatches to Anthropic or Google based on `LLM_PROVIDER`. Function-calling shape is identical on both sides.
- **Top-2 lineage** — the runner-up from each generation is carried into the next round-robin alongside the new champion. Stops the population from collapsing onto a single line of descent.
- **Win-rate selection** — promotion is by tournament-wide win rate (score / games_played) with random tiebreak. We started with a head-to-head gate against the prior champion, but with only 2 games per pair its variance could lock the demo on baseline indefinitely.
- **Static + dynamic candidate gating** — forbidden imports, hallucinated `chess.X` attributes, missing required structure, and a smoke game vs `RandomEngine` all run before a candidate enters the tournament. Most builder failures are caught in <1 s instead of corrupting a 5-minute round-robin.
- **Optional Modal tournament backend** — flip `TOURNAMENT_BACKEND=modal` in `.env` and each game runs in its own Modal container. Real OS-level parallelism and frees the local machine; warmup runs in parallel with strategist + builders so it's a net win on wall-clock.
- **Live dashboard** — every move, strategist question, and Elo update streams over WebSocket. `state.cleared` events let one client wipe everyone's view in lockstep.
- **Replay command** — `make replay` re-emits the persisted event stream over WS. Designed as a demo safety net for when the live run misbehaves.
- **Pure-code engine experiment** — the [experiment-pure-code-engines](experiment-pure-code.md) branch flips the design so the LLM *writes* a classical alpha-beta engine that plays in pure Python (no LLM at move time). ~50 ms per move instead of seconds, ~5 LLM calls per gen instead of ~1000.
