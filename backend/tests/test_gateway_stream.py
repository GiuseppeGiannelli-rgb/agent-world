"""Spec 11 T05: real streaming on /v1/chat/completions.

With "stream": true the gateway sends OpenAI `chat.completion.chunk` frames as
the provider (or the demo simulator) writes, then the chunk with its
`finish_reason` and the usage, then `data: [DONE]`. Before the first visible
words the router still fails over; after them a provider that breaks off ends
the stream with an error frame. No test reaches a real provider: the router's
HTTP client is a MockTransport whose streams wait on events the test sets, so a
chunk seen before the event proves nothing was buffered on the way."""

import asyncio
import contextlib
import json
import random
from pathlib import Path

import httpx
import pytest
import uvicorn

from backend.app import create_app
from backend.config import Config
from backend.router.index import Router
from backend.router.providers import THINK_RE, ThinkFilter
from backend.store import Store

REPO = Path(__file__).resolve().parents[2]
CHAT = [{"role": "system", "content": "[[role:chat]]\nYou are Ada, the CEO."}, {"role": "user", "content": "How is the team doing today?"}]


def no_keys(monkeypatch):
    default = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    for section in (default["providers"], default["media"]["providers"]):
        for p in section.values():
            for k in ("keyEnv", "baseUrlEnv"):
                if p.get(k):
                    monkeypatch.delenv(p[k], raising=False)
    monkeypatch.delenv("AGENT_WORLD_API_KEY", raising=False)


class Upstream(httpx.AsyncByteStream):
    """The body of a provider's SSE answer: strings go out as they are, an
    asyncio.Event holds the stream until the test sets it, an exception breaks it."""

    def __init__(self, items):
        self.items = items
        self.closed = asyncio.Event()

    async def __aiter__(self):
        for item in self.items:
            if isinstance(item, asyncio.Event):
                await item.wait()
            elif isinstance(item, BaseException):
                raise item
            else:
                yield item.encode()

    async def aclose(self):
        self.closed.set()


def oa(content=None, finish=None, usage=None, model="gpt-test") -> str:
    obj = {"model": model, "choices": [{"index": 0, "delta": {} if content is None else {"content": content}, "finish_reason": finish}]}
    if usage:
        obj = {"model": model, "choices": [], "usage": usage}
    return f"data: {json.dumps(obj)}\n\n"


class Fake:
    """A provider: answers per model name with an Upstream, a status or a callable."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.requests: list[dict] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "body": body})
        answer = self.answers[body["model"]]
        if callable(answer):
            answer = answer(body)
        if isinstance(answer, int):
            return httpx.Response(answer, json={"error": {"message": "upstream down"}})
        if isinstance(answer, tuple):
            return httpx.Response(answer[0], text=answer[1])
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=answer)


def make_app(tmp_path, monkeypatch, fake: Fake | None = None, keys=("OPENAI_API_KEY",)):
    no_keys(monkeypatch)
    monkeypatch.setenv("AGENT_WORLD_FAST", "1")
    for k in keys:
        monkeypatch.setenv(k, "sk-test")
    config = Config(REPO / "config")
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) if fake else None
    router = Router(config, tmp_path, client=client)
    return create_app(config=config, store=Store(tmp_path), router=router)


def asgi(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


def frames_of(text: str) -> list:
    out = []
    for f in (f for f in text.split("\n\n") if f.strip()):
        assert f.startswith("data: "), f
        data = f[len("data: ") :]
        out.append(data if data == "[DONE]" else json.loads(data))
    return out


def content(frames) -> str:
    return "".join(c["choices"][0]["delta"].get("content", "") for c in frames if isinstance(c, dict) and c.get("choices"))


@contextlib.asynccontextmanager
async def serve(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        app.state.shutdown.set()
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def post_stream(c: httpx.AsyncClient, model: str, messages=CHAT, **extra) -> tuple[int, list]:
    async with c.stream("POST", "/v1/chat/completions", json={"model": model, "stream": True, "messages": messages, **extra}) as res:
        text = "".join([part async for part in res.aiter_text()])
    return res.status_code, frames_of(text) if res.status_code == 200 else json.loads(text)


# ---------- the demo simulator streams ----------


@pytest.mark.asyncio
async def test_the_demo_answer_arrives_in_many_chunks_that_join_into_the_same_text(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, keys=())
    async with asgi(app) as c:
        whole = (await c.post("/v1/chat/completions", json={"model": "combo:fast", "messages": CHAT})).json()
        status, frames = await post_stream(c, "combo:fast")
    assert status == 200
    chunks = [f for f in frames if isinstance(f, dict)]
    pieces = [f for f in chunks if f["choices"][0]["delta"].get("content")]
    assert len(pieces) >= 3  # not one block at the end
    assert content(frames) == whole["choices"][0]["message"]["content"]
    assert pieces[0]["choices"][0]["delta"]["role"] == "assistant" and all("role" not in p["choices"][0]["delta"] for p in pieces[1:])
    assert {f["id"] for f in chunks} == {chunks[0]["id"]} and all(f["object"] == "chat.completion.chunk" for f in chunks)
    last = chunks[-1]
    assert last["choices"][0]["finish_reason"] == "stop" and last["choices"][0]["delta"] == {}
    assert last["usage"]["total_tokens"] == last["usage"]["prompt_tokens"] + last["usage"]["completion_tokens"] > 0
    assert all(f["choices"][0]["finish_reason"] is None for f in pieces)
    assert frames[-1] == "[DONE]"


@pytest.mark.asyncio
async def test_a_stream_is_logged_like_a_call(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, keys=())
    async with asgi(app) as c:
        await post_stream(c, "combo:fast")
    call = app.state.router.recent[0]
    assert call["ok"] and call["demo"] and call["agentId"] == "gateway" and call["tokens"]["out"] > 0


# ---------- a real provider, chunk by chunk ----------


@pytest.mark.asyncio
async def test_the_first_words_reach_the_client_before_the_provider_has_finished(tmp_path, monkeypatch):
    hold = asyncio.Event()
    upstream = Upstream([oa("Hello"), hold, oa(" world"), oa(finish="stop"), oa(usage={"prompt_tokens": 11, "completion_tokens": 2}), "data: [DONE]\n\n"])
    fake = Fake({"gpt-test": upstream})
    app = make_app(tmp_path, monkeypatch, fake)
    async with serve(app) as base, httpx.AsyncClient(base_url=base, timeout=10) as c:
        async with c.stream("POST", "/v1/chat/completions", json={"model": "openai/gpt-test", "stream": True, "messages": CHAT}) as res:
            assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
            reader = res.aiter_text()
            buf = ""
            while "\n\n" not in buf:
                buf += await asyncio.wait_for(reader.__anext__(), timeout=5)
            first = json.loads(buf.split("\n\n")[0][len("data: ") :])
            assert first["choices"][0]["delta"] == {"role": "assistant", "content": "Hello"}
            assert not hold.is_set()  # the provider is still writing: nothing waited for its end
            hold.set()
            async for part in reader:
                buf += part
    frames = frames_of(buf)
    assert content(frames) == "Hello world"
    end = frames[-2]
    assert end["choices"][0]["finish_reason"] == "stop" and end["usage"] == {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13}
    assert end["model"] == "openai/gpt-test"
    sent = fake.requests[0]["body"]
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True} and sent["messages"] == CHAT


@pytest.mark.asyncio
async def test_a_client_that_goes_away_closes_the_provider_stream(tmp_path, monkeypatch):
    hold = asyncio.Event()
    upstream = Upstream([oa("Hello"), hold, oa(" never read")])
    app = make_app(tmp_path, monkeypatch, Fake({"gpt-test": upstream}))
    async with serve(app) as base:
        async with httpx.AsyncClient(base_url=base, timeout=10) as c:
            async with c.stream("POST", "/v1/chat/completions", json={"model": "openai/gpt-test", "stream": True, "messages": CHAT}) as res:
                reader = res.aiter_text()
                assert "Hello" in await asyncio.wait_for(reader.__anext__(), timeout=5)
        # the connection is closed: the server stops reading the provider, it does not wait for it
        await asyncio.wait_for(upstream.closed.wait(), timeout=5)
    assert not hold.is_set()


@pytest.mark.asyncio
async def test_anthropic_streams_are_relayed_with_their_usage_and_their_stop_reason(tmp_path, monkeypatch):
    def ev(kind, **data):
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n"

    upstream = Upstream(
        [
            ev("message_start", message={"model": "claude-test", "usage": {"input_tokens": 25, "output_tokens": 1}}),
            ev("content_block_start", index=0, content_block={"type": "text", "text": ""}),
            ev("ping"),
            ev("content_block_delta", index=0, delta={"type": "text_delta", "text": "Bonjour"}),
            ev("content_block_delta", index=0, delta={"type": "text_delta", "text": " à tous"}),
            ev("content_block_stop", index=0),
            ev("message_delta", delta={"stop_reason": "max_tokens"}, usage={"output_tokens": 4}),
            ev("message_stop"),
        ]
    )
    fake = Fake({"claude-test": upstream})
    app = make_app(tmp_path, monkeypatch, fake, keys=("ANTHROPIC_API_KEY",))
    async with asgi(app) as c:
        status, frames = await post_stream(c, "anthropic/claude-test", max_tokens=4)
    assert status == 200 and content(frames) == "Bonjour à tous"
    end = frames[-2]
    assert end["choices"][0]["finish_reason"] == "length" and end["usage"] == {"prompt_tokens": 25, "completion_tokens": 4, "total_tokens": 29}
    sent = fake.requests[0]
    assert sent["url"].endswith("/messages") and sent["body"]["stream"] is True and sent["body"]["max_tokens"] == 4 and sent["body"]["system"] == CHAT[0]["content"]


@pytest.mark.asyncio
async def test_a_target_that_fails_before_its_first_words_hands_over_to_the_next(tmp_path, monkeypatch):
    fake = Fake({"model-a": 500, "model-b": Upstream([oa("from b"), oa(finish="stop"), "data: [DONE]\n\n"])})
    app = make_app(tmp_path, monkeypatch, fake)
    app.state.config.get()["combos"]["duo"] = {"strategy": "fallback", "models": ["openai/model-a", "openai/model-b"]}
    async with asgi(app) as c:
        status, frames = await post_stream(c, "combo:duo")
    assert status == 200 and content(frames) == "from b" and frames[0]["model"] == "openai/model-b"
    router = app.state.router
    assert router.cooldowns["openai/model-a"]["failures"] == 1 and router.stats["openai/model-a"]["fail"] == 1
    assert router.stats["openai/model-b"]["ok"] == 1


@pytest.mark.asyncio
async def test_an_empty_stream_counts_as_a_failure_and_the_next_target_answers(tmp_path, monkeypatch):
    fake = Fake({"model-a": Upstream([oa(""), oa(finish="stop"), "data: [DONE]\n\n"]), "model-b": Upstream([oa("ok"), "data: [DONE]\n\n"])})
    app = make_app(tmp_path, monkeypatch, fake)
    app.state.config.get()["combos"]["duo"] = {"strategy": "fallback", "models": ["openai/model-a", "openai/model-b"]}
    async with asgi(app) as c:
        status, frames = await post_stream(c, "combo:duo")
    assert status == 200 and content(frames) == "ok"
    assert "Empty answer" in app.state.router.stats["openai/model-a"]["lastError"]


@pytest.mark.asyncio
async def test_nobody_answering_is_a_502_before_any_chunk(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, Fake({"gpt-test": 503}))
    async with asgi(app) as c:
        status, body = await post_stream(c, "openai/gpt-test")
    assert status == 502 and body["error"]["type"] == "upstream_error" and "503" in body["error"]["message"]


@pytest.mark.asyncio
async def test_a_provider_that_breaks_off_mid_answer_ends_the_stream_with_an_error_frame(tmp_path, monkeypatch):
    upstream = Upstream([oa("Half an"), httpx.ReadError("connection reset")])
    app = make_app(tmp_path, monkeypatch, Fake({"gpt-test": upstream}))
    async with asgi(app) as c:
        status, frames = await post_stream(c, "openai/gpt-test")
    assert status == 200 and content(frames) == "Half an"
    assert frames[-2]["error"]["type"] == "upstream_error" and "connection reset" in frames[-2]["error"]["message"]
    assert frames[-1] == "[DONE]"
    assert app.state.router.stats["openai/gpt-test"]["fail"] == 1 and app.state.router.recent[0]["ok"] is False


@pytest.mark.asyncio
async def test_think_blocks_split_across_chunks_never_reach_the_client(tmp_path, monkeypatch):
    upstream = Upstream([oa("<thi"), oa("nk>the secret plan</th"), oa("ink>\n\nVisible"), oa(" answer"), "data: [DONE]\n\n"])
    app = make_app(tmp_path, monkeypatch, Fake({"gpt-test": upstream}))
    async with asgi(app) as c:
        status, frames = await post_stream(c, "openai/gpt-test")
    assert status == 200 and content(frames) == "Visible answer"


@pytest.mark.asyncio
async def test_a_server_that_refuses_stream_options_is_asked_again_without_them(tmp_path, monkeypatch):
    def answer(body):
        if "stream_options" in body:
            return (400, '{"error": {"message": "Unrecognized request argument supplied: stream_options"}}')
        return Upstream([oa("plain"), oa(" stream"), oa(finish="length"), "data: [DONE]\n\n"])

    fake = Fake({"gpt-test": answer})
    app = make_app(tmp_path, monkeypatch, fake)
    async with asgi(app) as c:
        status, frames = await post_stream(c, "openai/gpt-test", response_format={"type": "json_object"})
    assert status == 200 and content(frames) == "plain stream" and len(fake.requests) == 2
    assert "stream_options" not in fake.requests[1]["body"] and "response_format" not in fake.requests[1]["body"]
    end = frames[-2]
    # no usage from the server: estimated like the simulator, from the characters
    prompt = sum(len(m["content"]) for m in CHAT)
    assert end["choices"][0]["finish_reason"] == "length" and end["usage"]["prompt_tokens"] == -(-prompt // 4) and end["usage"]["completion_tokens"] == -(-len("plain stream") // 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_an_unknown_model_is_a_404_in_the_openai_shape(tmp_path, monkeypatch, stream):
    """Found with T05: before, a model that is neither a combo nor provider/model
    raised inside the router and the client got a bare 500."""
    from backend.i18n import http_error

    app = make_app(tmp_path, monkeypatch, keys=())
    async with asgi(app) as c:
        res = await c.post("/v1/chat/completions", json={"model": "nope", "stream": stream, "messages": CHAT})
    assert res.status_code == 404 and res.json() == {"error": {"message": http_error("en", "model_unknown", value=repr("nope")), "type": "invalid_request_error"}}


@pytest.mark.asyncio
async def test_the_stream_wants_the_key_like_the_rest_of_v1(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, keys=())
    monkeypatch.setenv("AGENT_WORLD_API_KEY", "secret-key")
    async with asgi(app) as c:
        status, _ = await post_stream(c, "combo:fast")
        assert status == 401
        async with c.stream("POST", "/v1/chat/completions", headers={"authorization": "Bearer secret-key"}, json={"model": "combo:fast", "stream": True, "messages": CHAT}) as res:
            assert res.status_code == 200


# ---------- the filter of <think> on pieces ----------

TEXTS = [
    "plain answer",
    "<think>hidden</think>shown",
    "a<THINK>x</Think>b<think>y\nz</think>c",
    "<think></think><think>two</think>end",
    "less < than and <thin k> not a tag",
    "trailing <think>t</think>",
]


@pytest.mark.parametrize("text", TEXTS)
def test_the_filter_drops_what_strip_thinking_drops_however_the_text_is_cut(text):
    want = THINK_RE.sub("", text)
    rnd = random.Random(7)
    cuts = [[i] for i in range(len(text) + 1)] + [sorted(rnd.sample(range(len(text) + 1), min(3, len(text) + 1))) for _ in range(40)]
    for cut in cuts:
        f, out, last = ThinkFilter(), "", 0
        for c in [*cut, len(text)]:
            out += f.feed(text[last:c])
            last = c
        assert out + f.flush() == want, (text, cut)


def test_an_unclosed_think_block_is_never_shown():
    f = ThinkFilter()
    assert f.feed("ok <think>the model was cut") + f.flush() == "ok "
