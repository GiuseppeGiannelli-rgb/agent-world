"""OpenAI-compatible gateway (/v1): mirrors the `gateway()` handler in
server/index.js.

Spec 11 T05: with "stream": true the answer goes out as the provider writes
it (Router.stream), one `chat.completion.chunk` per piece, then the chunk
with `finish_reason` and the usage, then `data: [DONE]`. Before the first
piece the router can still fail over to the next model, and an answer
nobody gives is a 502 like the non-streaming one; a provider that breaks off
mid-answer ends the stream with an `error` frame."""

import hmac
import json as jsonlib
import os
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.i18n import http_error, ui_language
from backend.plan import nz
from backend.router.providers import ProviderError


def _authorized(request: Request) -> bool:
    key = os.environ.get("AGENT_WORLD_API_KEY")
    if not key:
        return True
    # spec 07: a constant-time comparison, so the answer time says nothing about the key
    return hmac.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {key}".encode())


def _usage(u: dict) -> dict:
    return {"prompt_tokens": u["in"], "completion_tokens": u["out"], "total_tokens": u["in"] + u["out"]}


def _frame(obj) -> str:
    return f"data: {jsonlib.dumps(obj, ensure_ascii=False)}\n\n"


def mount(app, *, config, router) -> None:
    def _err(status: int, key: str, *, type: str | None = None, **vars) -> JSONResponse:
        """The OpenAI shape, the text in the language of the app (N13, spec 11 T02)."""
        return JSONResponse({"error": {"message": http_error(ui_language(config.get()), key, **vars), **({"type": type} if type else {})}}, status_code=status)

    @app.get("/v1/models")
    async def v1_models(request: Request):
        if not _authorized(request):
            return _err(401, "api_key_invalid")
        c = config.get()
        data = [{"id": f"combo:{name}", "object": "model", "owned_by": "agent-world"} for name in c["combos"]]
        for combo in c["combos"].values():
            for model_id in combo["models"]:
                data.append({"id": model_id, "object": "model", "owned_by": model_id.split("/")[0]})
        deduped = list({d["id"]: d for d in data}.values())
        return {"object": "list", "data": deduped}

    @app.post("/v1/chat/completions")
    async def v1_chat_completions(request: Request):
        if not _authorized(request):
            return _err(401, "api_key_invalid")
        body = await request.json()
        if not isinstance(body.get("messages"), list):
            return _err(400, "messages_required")
        use = str(nz(body.get("model"), f"combo:{config.get()['router']['defaultCombo']}"))
        try:
            router.expand(use)
        except ValueError:
            # spec 11 T05: neither a combo nor provider/model; before, a bare 500 from inside the router
            return _err(404, "model_unknown", type="invalid_request_error", value=repr(use))
        call = {
            "use": use,
            "messages": body["messages"],
            "json": (body.get("response_format") or {}).get("type") == "json_object",
            "max_tokens": nz(body.get("max_tokens"), body.get("max_completion_tokens")),
            "temperature": body.get("temperature"),
            "meta": {"agentId": "gateway"},
            "emergency": False,  # spec 08: a client gets an error, never an invented answer
        }
        if body.get("stream"):
            return await _stream(call)
        try:
            out = await router.chat(**call)
        except ProviderError as err:
            return JSONResponse({"error": {"message": str(err), "type": "upstream_error"}}, status_code=502)

        return {
            "id": f"chatcmpl-aw-{out['callId'][:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": out["target"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": out["text"]}, "finish_reason": "stop"}],
            "usage": _usage(out["usage"]),
        }

    async def _stream(call: dict):
        events = router.stream(**call)
        try:
            start = await events.__anext__()  # the first visible words of some model, or the error of all of them
        except ProviderError as err:
            return JSONResponse({"error": {"message": str(err), "type": "upstream_error"}}, status_code=502)
        # the id names the stream from its first chunk; the call's own id comes only at its end
        id_ = f"chatcmpl-aw-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        def chunk(delta: dict, finish: str | None) -> dict:
            return {"id": id_, "object": "chat.completion.chunk", "created": created, "model": start["target"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        async def frames():
            first = True
            try:
                async for ev in events:
                    if ev["type"] == "delta":
                        yield _frame(chunk({"role": "assistant", "content": ev["text"]} if first else {"content": ev["text"]}, None))
                        first = False
                    elif ev["type"] == "end":
                        yield _frame({**chunk({}, ev["finish"]), "usage": _usage(ev["usage"])})
                    elif ev["type"] == "error":
                        yield _frame({"error": {"message": ev["message"], "type": "upstream_error"}})
                yield "data: [DONE]\n\n"
            finally:
                await events.aclose()

        # no buffering on the way: a proxy (nginx) passes each chunk at once
        return StreamingResponse(frames(), media_type="text/event-stream", headers={"cache-control": "no-cache", "x-accel-buffering": "no"})
