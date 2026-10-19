"""OpenAI-compatible gateway (/v1): mirrors the `gateway()` handler in
server/index.js. Streaming replies in a single chunk (D7)."""

import hmac
import os
import time

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


def mount(app, *, config, router) -> None:
    def _err(status: int, key: str) -> JSONResponse:
        """The OpenAI shape, the text in the language of the app (N13, spec 11 T02)."""
        return JSONResponse({"error": {"message": http_error(ui_language(config.get()), key)}}, status_code=status)

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
            out = await router.chat(
                use=use,
                messages=body["messages"],
                json=(body.get("response_format") or {}).get("type") == "json_object",
                max_tokens=nz(body.get("max_tokens"), body.get("max_completion_tokens")),
                temperature=body.get("temperature"),
                meta={"agentId": "gateway"},
                emergency=False,  # spec 08: a client gets an error, never an invented answer
            )
        except ProviderError as err:
            return JSONResponse({"error": {"message": str(err), "type": "upstream_error"}}, status_code=502)

        id_ = f"chatcmpl-aw-{out['callId'][:12]}"
        created = int(time.time())
        usage = {"prompt_tokens": out["usage"]["in"], "completion_tokens": out["usage"]["out"], "total_tokens": out["usage"]["in"] + out["usage"]["out"]}

        if body.get("stream"):
            def chunk(delta, finish):
                return {"id": id_, "object": "chat.completion.chunk", "created": created, "model": out["target"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

            async def frames():
                import json as jsonlib

                yield f"data: {jsonlib.dumps(chunk({'role': 'assistant', 'content': out['text']}, None))}\n\n"
                yield f"data: {jsonlib.dumps({**chunk({}, 'stop'), 'usage': usage})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(frames(), media_type="text/event-stream")

        return {
            "id": id_,
            "object": "chat.completion",
            "created": created,
            "model": out["target"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": out["text"]}, "finish_reason": "stop"}],
            "usage": usage,
        }
