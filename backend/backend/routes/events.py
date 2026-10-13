"""GET /api/events: one SSE stream per client, fed by the shared Bus."""

import asyncio
import time

from fastapi import Request
from fastapi.responses import StreamingResponse

PING_INTERVAL_S = 15
DISCONNECT_POLL_S = 1.0


async def _stream(request: Request, bus, shutdown: asyncio.Event):
    queue, unsubscribe = bus.subscribe()
    try:
        yield "retry: 2000\n\n"
        last_sent = time.monotonic()
        while not shutdown.is_set():
            if await request.is_disconnected():
                return
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_POLL_S)
                yield frame
                last_sent = time.monotonic()
            except asyncio.TimeoutError:
                if time.monotonic() - last_sent >= PING_INTERVAL_S:
                    yield ": ping\n\n"
                    last_sent = time.monotonic()
    finally:
        unsubscribe()


def mount(app, *, bus, shutdown: asyncio.Event) -> None:
    @app.get("/api/events")
    async def api_events(request: Request):
        return StreamingResponse(_stream(request, bus, shutdown), media_type="text/event-stream")
