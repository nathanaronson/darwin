/**
 * useEventStream.ts — React hook that provides a unified CubistEvent log.
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
import type { CubistEvent } from "../api/events";

const STORAGE_KEY = "cubist.events.v1";

function loadPersisted(): CubistEvent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as CubistEvent[]) : [];
  } catch {
    return [];
  }
}

/**
 * Accumulates all {@link CubistEvent}s received since the component mounted.
 *
 * Activates mock mode when the URL contains `?mock` (any value); otherwise
 * connects to the live WebSocket endpoint proxied through Vite at `/ws`.
 *
 * @returns read-only, ever-growing array of events in arrival order
 *
 * @example
 * ```tsx
 * const events = useEventStream();
 * const questions = events.filter(e => e.type === "strategist.question");
 * ```
 */
export function useEventStream(): CubistEvent[] {
  // Mock mode is volatile by design; live mode rehydrates from localStorage so
  // a window reload mid-generation doesn't blank the dashboard. The backend
  // EventBus has no replay, so without this every refresh starts empty.
  const useMock =
    typeof location !== "undefined" &&
    new URLSearchParams(location.search).has("mock");
  const [events, setEvents] = useState<CubistEvent[]>(() =>
    useMock ? [] : loadPersisted(),
  );

  useEffect(() => {
    const push = (e: CubistEvent) =>
      setEvents((prev) => {
        const next = [...prev, e];
        if (!useMock) {
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
          } catch {
            // quota or serialization failure — drop the persistence write,
            // keep the in-memory log intact
          }
        }
        return next;
      });

    if (useMock) {
      return startMockStream(push);
    }

    const ws = connectEvents(push);
    return () => ws.close();
  }, [useMock]);

  return events;
}
