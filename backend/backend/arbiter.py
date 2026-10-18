"""Spec 09 §2.3: TypeSafe's Jev as the arbiter of a decision taken for the owner.

Jev is a "System One" model: it writes no text, it answers typed questions
with probabilities. Here one "choice" question: which of the options the lead
wrote unblocks the work best. POST {base}/systemone with the state of the
task and the options as criteria; the answer is a choice and its confidence.
The caller keeps the lead's pick when Jev is not configured, fails, or is
below router.arbiter.minConfidence: the arbiter can only improve a decision,
never block one."""

import logging
import os

from backend.router.providers import base_url

log = logging.getLogger("agent_world.arbiter")
TIMEOUT_S = 20
INSTRUCTIONS = "Which option unblocks the work best, consistent with the goal and the work already delivered, without needing anything more from the owner?"


def arbiter_ready(router) -> bool:
    cfg = (router.cfg.get("router") or {}).get("arbiter") or {}
    pid = cfg.get("provider", "typesafe")
    p = (router.cfg.get("providers") or {}).get(pid) or {}
    return p.get("kind") == "typesafe" and router.provider_ready(pid)


async def typesafe_choose(router, state: dict, options: list[dict]) -> dict | None:
    """{"choice", "confidence"} from Jev, or None (not configured, an error, an answer it cannot read)."""
    if len(options) < 2 or not arbiter_ready(router):
        return None
    cfg = (router.cfg.get("router") or {}).get("arbiter") or {}
    p = router.cfg["providers"][cfg.get("provider", "typesafe")]
    key = os.environ.get(p["keyEnv"], "") if p.get("keyEnv") else ""
    body = {
        "model": cfg.get("model", "jev-latest"),
        "state": state,
        "questions": {"solution": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": {o["id"]: f"{o['solution']} (why: {o['why']})" if o.get("why") else o["solution"] for o in options}}},
    }
    try:
        res = await router.client.post(base_url(p) + "/systemone", json=body, headers={"authorization": f"Bearer {key}", "content-type": "application/json"}, timeout=TIMEOUT_S)
        if res.status_code >= 400:
            log.warning("TypeSafe answered %s: the lead's pick stands", res.status_code)
            return None
        answers = res.json().get("answers") or {}
    except Exception as err:  # noqa: BLE001 -- the arbiter is a bonus: any failure keeps the lead's pick
        log.warning("TypeSafe unreachable (%s): the lead's pick stands", err)
        return None
    a = answers.get("solution") if isinstance(answers, dict) else next((x for x in answers if isinstance(x, dict) and x.get("name") == "solution"), None)
    if not isinstance(a, dict) or a.get("choice") is None:
        return None
    probs = a.get("probabilities") if isinstance(a.get("probabilities"), dict) else {}
    try:
        confidence = float(a.get("confidence") if a.get("confidence") is not None else probs.get(a["choice"], 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"choice": str(a["choice"]), "confidence": confidence}
