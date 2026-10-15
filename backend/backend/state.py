"""Assembles GET /api/state: real fields from Config/Store, typed stubs for
every subsystem not yet ported (A1). Each stub is replaced, not reshaped,
when its phase lands."""

PUBLIC_CONFIG_KEYS = ["ceo", "teams", "staff", "limits", "pacing", "router", "combos", "providers", "media", "skills", "ui"]

STUB_AGENTS: list = []
STUB_ROUTER = {"mode": "demo", "providers": [], "combos": [], "recent": []}
STUB_MEDIA = {"ready": False, "image": [], "speech": []}
STUB_SKILLS = {"count": 0, "sources": []}
STUB_BRAIN = {"count": 0, "recent": []}


def public_config(config) -> dict:
    v = config.get()
    return {k: v[k] for k in PUBLIC_CONFIG_KEYS}


def run_list(store) -> list[dict]:
    out = []
    for r in store.list():
        out.append(
            {
                "id": r["id"],
                "goal": r.get("goal"),
                "status": r.get("status"),
                "mode": r.get("mode"),
                "createdAt": r.get("createdAt"),
                "finishedAt": r.get("finishedAt"),
                "complexity": r.get("complexity"),
                "workstreams": len(r.get("workstreams") or []),
                "tasks": len(r.get("tasks") or []),
                "done": len([t for t in (r.get("tasks") or []) if t.get("status") == "done"]),
            }
        )
    return out


def build_state(config, store, live_run=None, *, router=None, skills=None, brain=None, team=None, media=None) -> dict:
    runs = store.list()
    current = live_run if live_run is not None else (runs[0] if runs else None)
    return {
        "mode": router.mode() if router is not None else "demo",
        "config": public_config(config),
        # P5: real team roster and media status replaced the A1 stubs.
        "agents": team.list() if team is not None else STUB_AGENTS,
        "run": current,
        "runs": run_list(store),
        "router": router.snapshot() if router is not None else STUB_ROUTER,
        "media": media.status() if media is not None else STUB_MEDIA,
        "skills": skills.summary() if skills is not None else STUB_SKILLS,
        "brain": {"count": brain.count, "recent": brain.list(40)} if brain is not None else STUB_BRAIN,
    }
