"""Mirrors the Node bus: emit() assigns seq and serializes once, then fans
out to one asyncio.Queue per SSE client. A full queue (a slow client) is
dropped, not blocked (B3) -- the others never wait on it."""

import asyncio
import json

FORWARD = {
    "chat", "run", "task", "workstream", "subtasks", "agent", "agent.spawn", "agent.despawn",
    "message", "plan", "file", "waiting", "brain", "skills", "run.done", "router.call", "config",
}


class Bus:
    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        self._seq = 0
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self._queues.add(queue)

        def unsubscribe():
            self._queues.discard(queue)

        return queue, unsubscribe

    def emit(self, type: str, payload) -> None:
        self._seq += 1
        frame = f"data: {json.dumps({'seq': self._seq, 'type': type, 'payload': payload})}\n\n"
        for queue in list(self._queues):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                self._queues.discard(queue)
