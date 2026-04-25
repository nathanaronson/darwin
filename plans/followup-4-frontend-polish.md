# Follow-up 4 — Frontend: live-board streaming + termination badges

**Owner:** TBD  •  **Branch:** `followup/frontend-polish`

## Why

On the last gen 2 run, the `LiveBoard` component stayed on
"Waiting for first game…" despite the backend firing
`game.move` events during the tournament. The generation also finished
quickly (all games timed out after 0–1 moves), and the
`GenerationTimeline` just showed "KEPT" / "PROMOTED" badges with no
indication that **every single game had terminated on `time` because of
a bug** — the UI happily declared gen 2 a success story.

Two gaps:

1. **Live board isn't rendering the move stream.** Either events are
   being filtered out before they reach `LiveBoard`, or the component's
   `useMemo` that reduces moves into a board state is stale after
   `game.finished` fires.
2. **Termination reasons are invisible.** `game.finished` carries a
   `termination` field (`checkmate` / `stalemate` / `time` /
   `max_moves` / `illegal_move` / `error`) but the UI never displays
   it. A tournament where every game ended on `time` should look
   alarming on the dashboard, not triumphant.

## What to do

### 1. Debug LiveBoard

Open `frontend/src/components/LiveBoard.tsx`. Check the selector that
picks the "current" game — it likely keys on the most recent
`game.move`, but if no `game.move` events are arriving (the backend's
round-robin completes too fast, or they're getting filtered), the
component never leaves the empty state.

Add a debug log (`console.debug("LiveBoard events:", events.filter(e => e.type.startsWith("game.")))`)
and run with the live backend. Confirm whether `game.move` events
reach the component; if not, inspect `useEventStream` and `App.tsx`
for filtering.

If the events **are** arriving, the bug is in the move→board-state
reducer.

### 2. Surface termination in the Timeline + Bracket

The `GenerationTimeline` row shows `PROMOTED` / `KEPT`. Add a
termination-breakdown subline underneath: "6 games: 5 time, 1 error".
Add it to `Bracket` too — each pairing cell should tint red when any
game in it ended on `time`, `error`, or `illegal_move`.

New helper in `GenerationTimeline.tsx`:

```ts
function terminationSummary(events: DarwinEvent[], gen: number): string {
  const finishes = events.filter(
    (e): e is GameFinished =>
      e.type === "game.finished" && /* filter by gen */ true
  );
  const counts: Record<string, number> = {};
  for (const f of finishes) counts[f.termination] = (counts[f.termination] ?? 0) + 1;
  return Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ");
}
```

### 3. Builder error tooltips in StrategistFeed

`builder.completed` events with `ok: false` currently show an "✗" in
the feed but hide the `error` string. Render it under the question
text, maybe truncated to 2 lines with full text on hover.

## Done when

- [ ] `LiveBoard` renders moves in real time during a live generation.
- [ ] Each `GenerationTimeline` row shows a termination breakdown.
- [ ] `Bracket` pairings with non-natural terminations are visually flagged.
- [ ] Builder error messages surface in `StrategistFeed` tooltips.

## Files to touch

- `frontend/src/components/LiveBoard.tsx`
- `frontend/src/components/GenerationTimeline.tsx`
- `frontend/src/components/Bracket.tsx`
- `frontend/src/components/StrategistFeed.tsx`
- `frontend/src/hooks/useEventStream.ts` (only if a filter bug is found there)

## Do **not** touch

- `frontend/src/api/events.ts` (frozen contract — mirror of backend/websocket.py).
- The backend — all needed data is already in `game.finished` events.
