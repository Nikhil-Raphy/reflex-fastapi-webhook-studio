# ADR-0004: Live push through an event bus

## Status

Accepted

## Context

A captured request must appear in an open inspector at once, with no refresh. With several workers, the worker that
catches a request is often not the worker that holds a given browser tab's websocket.

Reflex runs background event handlers that can change a tab's state and push the change over its websocket. When
`REFLEX_REDIS_URL` is set, Reflex keeps state in Redis and can run several workers, and
`reflex.utils.prerequisites.get_redis()` returns its async Redis client.

## Decision

- `bus/base.py` defines the contract: `EventBus.publish(event)` and `EventBus.subscribe(bin_id)`, an async context
  that yields a `Subscription`. `Subscription.next(wait_s)` returns the next `BinEvent`, or `None` after `wait_s`
  seconds with none.
- Events are `BinEvent` values from `domain.py`. Their `EventType` is `request.captured`, carrying the request's
  summary, or `bin.updated`, carrying the new label. A bus gives a subscriber `resync` when it may have missed
  events.
- `MemoryBus` gives each subscriber an `asyncio.Queue` of 256 events. When a queue is full, the bus empties it and
  queues one `resync`, since a reload from the database covers every event it held.
- `RedisBus` publishes each event as JSON on the channel `webhook-studio:bin:{bin_id}`. Each worker runs one pattern
  listener, as a Reflex lifespan task, that feeds the worker's own `MemoryBus`. After the listener loses Redis and
  reconnects, it gives every subscriber `resync`. A failed publish is logged and never fails the request.
- `runtime.py` picks the bus at start: `RedisBus` with Reflex's Redis client when `REFLEX_REDIS_URL` is set,
  otherwise `MemoryBus`. The API and the UI share it.
- `CaptureService` publishes `request.captured` after it stores a request. `BinService.rename` publishes
  `bin.updated`.
- Each open inspector runs one background task, `InspectorState.watch`, started by the page's `on_load`:
  - It records `{worker id}:{bin id}` in a backend var, and returns at once if that key is already there, so a tab
    runs one task. A task stops when the key changes, such as when the tab moves to another bin.
  - It subscribes first and then reloads from the database, so no event falls between the two, and skips requests
    that are already listed.
  - Every 15 s with no event, it checks that the tab still holds a websocket on this worker, through
    `app.event_namespace.token_to_sid`, and stops if not.
  - On `resync` it reloads from the database.
- A dot on the inspector shows the live state: green ("Live") when the task follows the bin, amber ("Connecting")
  while the websocket reconnects or before the task starts, and red ("Offline") after repeated connection errors.

## Consequences

- New requests show in about the time a websocket message takes, with no polling.
- Locally nothing beyond Reflex is needed. With Redis, the Redis that Reflex already uses carries the events, and
  the app needs no Redis package of its own.
- Redis pub/sub keeps no messages, so missed events are made good by reloading: on `resync`, and each time a tab
  reconnects, because Reflex then rehydrates the page and runs its `on_load` handlers again.
- A watch task runs on the worker that holds its tab's websocket, since the event that starts it arrives over that
  socket. If the tab reconnects to another worker, the new worker's task takes over and the old one stops at its next
  heartbeat.
- Health checks Redis when the app uses it.
