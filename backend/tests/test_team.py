class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


STAFF = [
    {"id": "ada", "name": "Ada", "team": "ceo", "kind": "ceo"},
    {"id": "rino", "name": "Rino", "team": "research", "kind": "lead"},
    {"id": "sara", "name": "Sara", "team": "research", "kind": "worker"},
]


def test_load_creates_and_updates_agents():
    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    assert team.get("ada")["kind"] == "ceo"
    assert len(team.list()) == 3
    team.load([{"id": "ada", "name": "Ada Nuova", "team": "ceo", "kind": "ceo"}])
    assert team.get("ada")["name"] == "Ada Nuova"
    assert team.get("rino") is None  # dropped: not busy, not a sub


def test_load_keeps_busy_agents_not_in_new_staff():
    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    team.take(team.get("rino"), "run1")
    team.load([STAFF[0]])
    assert team.get("rino") is not None  # busy, so kept even though dropped from staff


def test_try_acquire_worker_then_lead_then_spawn():
    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    a = team.try_acquire("research", "run1")
    assert a["id"] == "sara"  # worker first
    b = team.try_acquire("research", "run1")
    assert b["id"] == "rino"  # then the lead
    c = team.try_acquire("research", "run1", allow_lead=True, spawn_limit=1)
    assert c["kind"] == "sub"
    assert c["id"] == "research-sub1"
    d = team.try_acquire("research", "run1", allow_lead=True, spawn_limit=1)
    assert d is None  # spawn limit reached


def test_despawn_removes_only_subs():
    from backend.team import Team

    bus = Bus()
    team = Team(bus)
    team.load(STAFF)
    sub = team.try_acquire("research", "run1", spawn_limit=1)
    team.try_acquire("research", "run1")  # take sara
    team.try_acquire("research", "run1")  # take rino
    team.despawn(sub["id"])
    assert team.get(sub["id"]) is None
    assert ("agent.despawn", {"id": sub["id"], "team": "research"}) in bus.events
    team.despawn("ada")  # not a sub: no-op
    assert team.get("ada") is not None


async def test_release_hands_to_waiter_first():
    import asyncio

    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    team.try_acquire("research", "run1")  # sara (worker)
    worker = team.try_acquire("research", "run1")  # rino (lead): now nobody is free
    task = asyncio.create_task(team.acquire("research", "run2"))
    await asyncio.sleep(0)  # nobody free: it must register as a waiter, not return at once
    team.release(worker["id"])
    got = await task
    assert got["id"] == worker["id"] == "rino"


async def test_acquire_can_be_cancelled_and_removes_its_waiter():
    import asyncio

    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    team.try_acquire("research", "run1")  # take sara, so research has no free worker
    team.try_acquire("research", "run1")  # take rino too
    task = asyncio.create_task(team.acquire("research", "run2"))
    await asyncio.sleep(0)
    assert len(team.waiters) == 1
    task.cancel()
    with __import__("pytest").raises(asyncio.CancelledError):
        await task
    assert team.waiters == []


def test_release_sub_despawns_when_no_waiter():
    from backend.team import Team

    bus = Bus()
    team = Team(bus)
    team.load(STAFF)
    sub = team.try_acquire("research", "run1", spawn_limit=1)
    team.release(sub["id"])
    assert team.get(sub["id"]) is None


def test_release_worker_resets_state():
    from backend.team import Team

    team = Team(Bus())
    team.load(STAFF)
    worker = team.try_acquire("research", "run1")
    team.set(worker["id"], {"state": "working", "text": "x"})
    team.release(worker["id"], {"verdict": "pass"})
    a = team.get(worker["id"])
    assert a["busy"] is False
    assert a["state"] == "idle"
    assert a["verdict"] == "pass"


async def test_release_skips_cancelled_waiters():
    """P7 regression: Node removes an aborted acquire waiter synchronously, but
    asyncio delivers cancellation a loop turn later. If a release lands in
    between (Run.start()'s shutdown finally), the agent must NOT be handed to
    the dead waiter -- that orphaned vera (qa) as idle+busy forever after
    stop()."""
    import asyncio

    from backend.team import Team

    team = Team(Bus())
    team.load([{"id": "judy", "name": "Judy", "team": "qa", "kind": "lead"}])
    team.take(team.get("judy"), "run1")  # nobody free in qa now

    waiter_task = asyncio.ensure_future(team.acquire("qa", "run1"))
    await asyncio.sleep(0)  # let the waiter register
    waiter_task.cancel()
    # NOTE: cancellation has not been delivered to the task yet -- the waiter
    # is still in team.waiters, exactly like during Run.stop().
    team.release("judy")
    await asyncio.sleep(0)  # now the cancellation lands

    judy = team.get("judy")
    assert judy["busy"] is False  # not handed to the dead waiter
    assert judy["runId"] is None
    assert team.waiters == []  # the cancelled waiter is gone


async def test_abort_waiters_cancels_synchronously():
    """P7 regression: Run.stop() calls abort_waiters, which cancels pending
    acquires IMMEDIATELY (like Node's synchronous abort listener). A release
    right after must find no waiter to hand the agent to."""
    import asyncio

    from backend.team import Team

    team = Team(Bus())
    team.load([{"id": "judy", "name": "Judy", "team": "qa", "kind": "lead"}])
    team.take(team.get("judy"), "run1")

    waiter_task = asyncio.ensure_future(team.acquire("qa", "run1"))
    await asyncio.sleep(0)  # waiter registered
    team.abort_waiters("run1")
    # the future is already done (cancelled): no delivery needed, no window
    team.release("judy")
    with __import__("pytest").raises(asyncio.CancelledError):
        await waiter_task

    judy = team.get("judy")
    assert judy["busy"] is False and judy["runId"] is None
    assert team.waiters == []


async def test_release_skips_waiters_of_aborted_runs():
    """P7 regression: a waiter whose run is aborted must never receive an
    agent, even if its cancellation has not been delivered yet (and even if
    abort_waiters was never called). Otherwise stop() can hand a judge to a
    dead run and leak it busy forever."""
    import asyncio

    from backend.team import Team

    team = Team(Bus())
    team.load([{"id": "judy", "name": "Judy", "team": "qa", "kind": "lead"}])
    team.take(team.get("judy"), "run1")

    abort = asyncio.Event()
    waiter_task = asyncio.ensure_future(team.acquire("qa", "run1", abort=abort))
    await asyncio.sleep(0)  # waiter registered
    abort.set()  # the run stops; the waiter is still pending and registered
    team.release("judy")

    judy = team.get("judy")
    assert judy["busy"] is False and judy["runId"] is None
    waiter_task.cancel()  # clean up the pending wait
    try:
        await waiter_task
    except asyncio.CancelledError:
        pass
