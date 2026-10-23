"""Tests for the in-process event bus."""

import pytest
from redis.asyncio import Redis

from reflex_fastapi_webhook_studio.bus.base import EventBus, Subscription
from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus, MemorySubscription
from reflex_fastapi_webhook_studio.bus.redis_bus import RedisBus
from reflex_fastapi_webhook_studio.domain import BinEvent, EventType

BIN = "AbCdEfGhIjKlMnOpQrStUv"
OTHER = "ZyXwVuTsRqPoNmLkJiHgFe"


def test_given_buses_when_checked_against_the_contract_then_both_fit() -> None:
    """Given the memory and Redis buses, when checked against the bus contract, then both fit it."""
    # Given
    buses = [MemoryBus(), RedisBus(Redis())]
    # When
    fits = [isinstance(bus, EventBus) for bus in buses]
    # Then
    assert fits == [True, True]
    assert isinstance(MemorySubscription(BIN, 1), Subscription)


def renamed(bin_id: str, label: str) -> BinEvent:
    """Build a `bin.updated` event.

    Args:
        bin_id: The bin id.
        label: The new label.

    Returns:
        The event.
    """
    return BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_id, label=label)


@pytest.mark.anyio
async def test_given_subscriber_when_events_are_published_then_it_gets_only_its_bin_in_order() -> None:
    """Given a subscriber of one bin, when events for it and another bin come, then it gets its own in order."""
    # Given
    bus = MemoryBus()
    async with bus.subscribe(BIN) as events:
        # When
        await bus.publish(renamed(BIN, "a"))
        await bus.publish(renamed(OTHER, "x"))
        await bus.publish(renamed(BIN, "b"))
        got = [await events.next(1), await events.next(1), await events.next(0.01)]
    # Then
    assert got == [renamed(BIN, "a"), renamed(BIN, "b"), None]


@pytest.mark.anyio
async def test_given_slow_subscriber_when_queue_fills_then_it_gets_one_resync_then_new_events() -> None:
    """Given a subscriber whose queue is full, when more events arrive, then it gets one resync, then later events."""
    # Given
    bus = MemoryBus(queue_size=2)
    async with bus.subscribe(BIN) as events:
        await bus.publish(renamed(BIN, "1"))
        await bus.publish(renamed(BIN, "2"))
        # When
        await bus.publish(renamed(BIN, "3"))
        await bus.publish(renamed(BIN, "4"))
        got = [await events.next(1), await events.next(1), await events.next(0.01)]
    # Then
    assert got == [BinEvent(type=EventType.RESYNC, bin_id=BIN), renamed(BIN, "4"), None]


@pytest.mark.anyio
async def test_given_two_subscribers_when_one_leaves_then_the_other_still_gets_events() -> None:
    """Given two subscribers of a bin, when one leaves, then the other still gets events and resyncs."""
    # Given
    bus = MemoryBus()
    async with bus.subscribe(BIN) as staying:
        async with bus.subscribe(BIN):
            pass
        # When
        await bus.publish(renamed(BIN, "a"))
        bus.resync_all()
        got = [await staying.next(1), await staying.next(1)]
    # Then
    assert got == [renamed(BIN, "a"), BinEvent(type=EventType.RESYNC, bin_id=BIN)]
