"""Tests for darwin.api.websocket.EventBus.

The bus is the in-process pub/sub fanout that connects orchestration code
(emit) to /ws connections (subscribe). It is critical that:

  - Multiple subscribers receive every event.
  - Backpressure on a slow subscriber doesn't stall emits to other
    subscribers (the dropped-event fallback).
  - Unsubscribe is idempotent and leaves the bus clean.
  - Emit shape matches the Envelope contract the frontend decoder expects.
"""

from __future__ import annotations

import asyncio

import pytest

from darwin.api.websocket import (
    Envelope,
    EventBus,
    GenerationFinished,
    GenerationStarted,
    StateCleared,
    StrategistQuestion,
)


@pytest.mark.asyncio
async def test_subscribe_returns_distinct_queues():
    """Two subscribe() calls must produce independent queues."""
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    assert q1 is not q2


@pytest.mark.asyncio
async def test_emit_broadcasts_to_all_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()

    payload = {"type": "generation.started", "number": 7, "champion": "x"}
    await bus.emit(payload)

    assert q1.qsize() == 1
    assert q2.qsize() == 1
    env1 = q1.get_nowait()
    env2 = q2.get_nowait()
    assert env1 == env2 == {"event": payload}


@pytest.mark.asyncio
async def test_emit_wraps_in_envelope_shape():
    """Frontend decodes `event.type` — wrapping shape is contractual."""
    bus = EventBus()
    q = bus.subscribe()

    await bus.emit({"type": "state.cleared"})

    msg = q.get_nowait()
    assert set(msg.keys()) == {"event"}
    assert msg["event"]["type"] == "state.cleared"


@pytest.mark.asyncio
async def test_emit_preserves_ordering_per_subscriber():
    bus = EventBus()
    q = bus.subscribe()

    for n in range(5):
        await bus.emit({"type": "generation.started", "number": n, "champion": "c"})

    received = [q.get_nowait()["event"]["number"] for _ in range(5)]
    assert received == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe()

    bus.unsubscribe(q)
    await bus.emit({"type": "state.cleared"})

    assert q.qsize() == 0


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent():
    """Calling unsubscribe twice on the same queue must not raise."""
    bus = EventBus()
    q = bus.subscribe()

    bus.unsubscribe(q)
    bus.unsubscribe(q)  # second call is documented as safe


@pytest.mark.asyncio
async def test_unsubscribe_unknown_queue_is_safe():
    bus = EventBus()
    foreign = asyncio.Queue()
    bus.unsubscribe(foreign)  # never subscribed; must not raise


@pytest.mark.asyncio
async def test_emit_with_no_subscribers_is_noop():
    bus = EventBus()
    await bus.emit({"type": "state.cleared"})  # no exception, no awaiting required


@pytest.mark.asyncio
async def test_full_subscriber_does_not_block_others():
    """Backpressure policy: a stalled subscriber drops events for itself
    only — emits to other subscribers must still go through."""
    bus = EventBus()
    healthy = bus.subscribe()
    stuck = bus.subscribe()

    # Fill the stuck queue past its 1000 capacity. We use a fast loop
    # rather than 1001 emits so the test stays sub-second.
    for _ in range(stuck.maxsize):
        stuck.put_nowait({"event": {"type": "state.cleared"}})

    await bus.emit({"type": "generation.started", "number": 1, "champion": "c"})

    # Healthy subscriber received the new event.
    assert healthy.qsize() == 1
    assert healthy.get_nowait()["event"]["number"] == 1
    # Stuck subscriber did NOT get a 1001st item — the bus dropped silently.
    assert stuck.qsize() == stuck.maxsize


@pytest.mark.asyncio
async def test_subscribers_set_grows_and_shrinks():
    """Internal _subscribers state should track active subscriptions."""
    bus = EventBus()
    assert len(bus._subscribers) == 0
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    assert len(bus._subscribers) == 2
    bus.unsubscribe(q1)
    assert len(bus._subscribers) == 1
    bus.unsubscribe(q2)
    assert len(bus._subscribers) == 0


def test_envelope_validates_known_event_types():
    """Pydantic must accept every Event variant when wrapped."""
    cases = [
        GenerationStarted(number=1, champion="x"),
        StrategistQuestion(index=0, category="search", text="x"),
        GenerationFinished(number=1, new_champion="x", elo_delta=12.5, promoted=True),
        StateCleared(),
    ]
    for evt in cases:
        env = Envelope(event=evt)
        assert env.event.type == evt.type


def test_envelope_rejects_unknown_event_type():
    """Discriminated union must reject types it doesn't know."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        Envelope.model_validate({"event": {"type": "not.a.real.event"}})


def test_generation_finished_ratings_default_to_empty_dict():
    """Older payloads (pre-ratings field) must still validate; default {}."""
    g = GenerationFinished(number=1, new_champion="x", elo_delta=0.0, promoted=False)
    assert g.ratings == {}
