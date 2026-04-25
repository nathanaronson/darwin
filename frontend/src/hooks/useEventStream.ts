/**
 * useEventStream.ts — React hook that provides a unified DarwinEvent log.
 *
 * Transparently switches between two event sources:
 *   - **Mock mode** (`?mock` in the URL): drives the UI from {@link startMockStream}
 *     so the dashboard can be developed and demoed without a live backend.
 *   - **Live mode** (default): opens a WebSocket via {@link connectEvents} and
 *     forwards every envelope's inner event into the accumulated state array.
 *
 * The returned array grows monotonically — events are never removed. All
 * components filter this array client-side, which keeps state management
 * trivially simple and avoids prop-drilling a complex store.
 *
 * @module useEventStream
 */

import { useEffect, useState } from "react";
import { connectEvents } from "../api/client";
import { startMockStream } from "./mockEvents";
import type { DarwinEvent } from "../api/events";

const STORAGE_KEY = "darwin.events.v1";

/** Read the persisted event log from localStorage. Tolerant of corruption
 *  — if anything is off (missing, not JSON, not an array) we treat it as
 *  empty and let the live WS catch us up.
 */
function loadPersisted(): DarwinEvent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DarwinEvent[]) : [];
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
        const next = [...prev, e];
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
