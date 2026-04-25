/**
 * useEventStream.ts — React hook that provides a unified DarwinEvent log.
 *
 * Transparently switches between two event sources:
 *   - **Mock mode** (`?mock` in the URL): drives the UI from {@link startMockStream}
 *     so the dashboard can be developed and demoed without a live backend.
 *   - **Live mode** (default): opens a WebSocket via {@link connectEvents} and
 *     forwards every envelope's inner event into the accumulated state array.
 *
 * Memory note: ``game.move`` events from finished generations are pruned
 * the moment a new ``generation.started`` arrives, so the in-memory log
 * stays bounded to roughly one generation's worth of moves (~7k events
 * × ~300B = ~2MB). All other event types — generation lifecycle,
 * strategist questions, builder/adversary/fixer outcomes — are kept
 * forever so the Elo charts, timeline, and header stats retain full
 * history. LiveBoards already scopes itself to the latest generation
 * boundary, so dropping prior gens' move events doesn't affect it.
 *
 * @module useEventStream
 */

import { useEffect, useState } from "react";
import { connectEvents } from "../api/client";
import { startMockStream } from "./mockEvents";
import type { DarwinEvent } from "../api/events";

const STORAGE_KEY = "darwin.events.v1";

/**
 * Drop ``game.move`` events that belong to a generation that already
 * ended. The "current" generation is whatever follows the most recent
 * ``generation.started`` in the array; any ``game.move`` before that
 * boundary is from a finished or cancelled gen and is dead weight.
 *
 * Returns the original array reference if nothing changed (lets React
 * skip unnecessary re-renders).
 */
function pruneStaleMoves(events: DarwinEvent[]): DarwinEvent[] {
  let lastGenStartIdx = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "generation.started") {
      lastGenStartIdx = i;
      break;
    }
  }
  if (lastGenStartIdx <= 0) return events;

  let needsPrune = false;
  for (let i = 0; i < lastGenStartIdx; i++) {
    if (events[i].type === "game.move") {
      needsPrune = true;
      break;
    }
  }
  if (!needsPrune) return events;

  const out: DarwinEvent[] = [];
  for (let i = 0; i < events.length; i++) {
    if (i < lastGenStartIdx && events[i].type === "game.move") continue;
    out.push(events[i]);
  }
  return out;
}

/** Read the persisted event log from localStorage. Tolerant of corruption
 *  — if anything is off (missing, not JSON, not an array) we treat it as
 *  empty and let the live WS catch us up. Also runs the same stale-move
 *  pruning the live path uses, so a saturated localStorage from a prior
 *  session doesn't immediately re-bloat the in-memory log on reload.
 */
function loadPersisted(): DarwinEvent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return pruneStaleMoves(parsed as DarwinEvent[]);
  } catch {
    return [];
  }
}

/**
 * Accumulates all {@link DarwinEvent}s received since the component mounted.
 *
 * Activates mock mode when the URL contains `?mock` (any value); otherwise
 * connects to the live WebSocket endpoint proxied through Vite at `/ws`.
 *
 * In live mode the event log is mirrored into localStorage so a page
 * reload (or a tab opened mid-generation) doesn't blank the dashboard.
 * The backend's EventBus has no replay; without persistence, anything
 * emitted before the WS subscriber connected is lost forever.
 *
 * @returns read-only, ever-growing array of events in arrival order
 */
export function useEventStream(): DarwinEvent[] {
  // Mock mode is volatile by design (dev demo flow rebuilds from scratch
  // every reload). Live mode rehydrates from localStorage.
  const useMock =
    typeof location !== "undefined" &&
    new URLSearchParams(location.search).has("mock");
  const [events, setEvents] = useState<DarwinEvent[]>(() =>
    useMock ? [] : loadPersisted(),
  );

  useEffect(() => {
    const persist = (next: DarwinEvent[]) => {
      if (useMock) return;
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Quota exceeded or serialization failure — drop the persistence
        // write but keep the in-memory log intact so the UI still updates.
      }
    };

    // ``state.cleared`` is a control event from the backend's
    // ``/api/state/clear`` endpoint — it tells us the DB has been wiped
    // and we should drop everything we've accumulated so the dashboard
    // matches the now-empty server state. We swallow the event itself
    // (don't append it) since downstream panels don't need to render it.
    const push = (e: DarwinEvent) => {
      if (e.type === "state.cleared") {
        setEvents([]);
        persist([]);
        return;
      }
      setEvents((prev) => {
        const appended = [...prev, e];
        // A new generation boundary lets us drop prior gens' move
        // events. Skip the prune work for every other event type to
        // keep the hot append path O(1) amortized.
        const next =
          e.type === "generation.started"
            ? pruneStaleMoves(appended)
            : appended;
        persist(next);
        return next;
      });
    };

    if (useMock) {
      return startMockStream(push);
    }

    const ws = connectEvents(push);
    return () => ws.close();
  }, [useMock]);

  return events;
}
