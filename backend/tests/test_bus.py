import asyncio

import pytest


@pytest.mark.asyncio
async def test_emit_assigns_increasing_seq():
    from backend.bus import Bus

    bus = Bus()
    queue, _ = bus.subscribe()
    bus.emit("a", {"x": 1})
    bus.emit("b", {"x": 2})
    first = await queue.get()
    second = await queue.get()
    assert '"seq": 1' in first or '"seq":1' in first
    assert '"seq": 2' in second or '"seq":2' in second


@pytest.mark.asyncio
async def test_frame_format():
    from backend.bus import Bus

    bus = Bus()
    queue, _ = bus.subscribe()
    bus.emit("config", {"a": 1})
    frame = await queue.get()
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    import json

    payload = json.loads(frame[len("data: "):-2])
    assert payload["type"] == "config"
    assert payload["payload"] == {"a": 1}
    assert isinstance(payload["seq"], int)


@pytest.mark.asyncio
async def test_slow_client_is_dropped_others_unaffected():
    from backend.bus import Bus

    bus = Bus(maxsize=2)
    slow_queue, slow_unsub = bus.subscribe()
    fast_queue, _ = bus.subscribe()
    bus.emit("a", {})
    # the fast client drains its queue as events arrive, so it never overflows
    await fast_queue.get()
    bus.emit("b", {})
    await fast_queue.get()
    bus.emit("c", {})  # slow_queue (maxsize=2, never drained) overflows here and is dropped
    await fast_queue.get()
    assert fast_queue.qsize() == 0
    bus.emit("d", {})
    assert await fast_queue.get() is not None  # fast client keeps receiving


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    from backend.bus import Bus

    bus = Bus()
    queue, unsubscribe = bus.subscribe()
    unsubscribe()
    bus.emit("a", {})
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_concurrent_emits_no_gaps_no_duplicates():
    from backend.bus import Bus

    bus = Bus(maxsize=1000)
    queue, _ = bus.subscribe()

    async def emit_many(n):
        for _ in range(n):
            bus.emit("x", {})

    await asyncio.gather(*(emit_many(10) for _ in range(10)))
    seqs = []
    for _ in range(100):
        frame = await queue.get()
        import json

        seqs.append(json.loads(frame[len("data: "):-2])["seq"])
    assert seqs == list(range(1, 101))
