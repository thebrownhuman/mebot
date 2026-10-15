import json

import httpx
import pytest
import respx

from mebot.llm.base import LLMError
from mebot.llm.factory import build_client
from mebot.llm.providers import PROVIDERS, get_provider

KEY = "sk-test-SECRET-1234"
MSGS = [
    {"role": "system", "content": "be nice"},
    {"role": "user", "content": "hi"},
]


def sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


def openai_chunk(text: str) -> str:
    return json.dumps({"choices": [{"delta": {"content": text}}]})


async def collect(it) -> str:
    return "".join([c async for c in it])


# --- registry ------------------------------------------------------------------


def test_registry_has_all_providers():
    ids = {p.id for p in PROVIDERS}
    assert ids == {
        "openrouter",
        "gemini",
        "openai",
        "anthropic",
        "groq",
        "ollama",
        "openai_compatible",
    }
    assert get_provider("ollama").key_required is False
    assert get_provider("openai_compatible").key_required is False
    assert get_provider("openai_compatible").base_url_required is True
    assert all(get_provider(i).key_required for i in ("openrouter", "gemini", "openai", "groq"))
    assert get_provider("gemini").default_base_url.startswith(
        "https://generativelanguage.googleapis.com/v1beta/openai"
    )


# --- openai-compatible (openai / openrouter / groq / gemini / custom) ----------


@respx.mock
async def test_openai_stream_request_shape_and_sse():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=sse(openai_chunk("Hel"), openai_chunk("lo"), "[DONE]"),
            headers={"content-type": "text/event-stream"},
        )
    )
    client = build_client("openai", api_key=KEY)
    out = await collect(
        client.stream_chat(MSGS, model="gpt-4o-mini", temperature=0.3, max_tokens=50)
    )
    assert out == "Hello"
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body == {
        "model": "gpt-4o-mini",
        "messages": MSGS,
        "stream": True,
        "temperature": 0.3,
        "max_tokens": 50,
        "stream_options": {"include_usage": True},
    }


@respx.mock
async def test_gemini_uses_openai_compat_endpoint():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    ).mock(return_value=httpx.Response(200, content=sse(openai_chunk("ok"), "[DONE]")))
    client = build_client("gemini", api_key=KEY)
    assert (
        await collect(
            client.stream_chat(MSGS, model="gemini-2.5-flash", temperature=0.4, max_tokens=10)
        )
        == "ok"
    )
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_custom_base_url_without_key():
    route = respx.post("http://llm.local:9000/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=sse(openai_chunk("x"), "[DONE]"))
    )
    client = build_client("openai_compatible", base_url="http://llm.local:9000/v1/")
    assert await collect(client.stream_chat(MSGS, model="m", temperature=0, max_tokens=5)) == "x"
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_openai_test_call_is_tiny_and_reports_latency():
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "p"}}]})
    )
    result = await build_client("openrouter", api_key=KEY).test(model="some/model")
    assert result.ok and result.latency_ms >= 0
    body = json.loads(route.calls.last.request.content)
    assert body["max_tokens"] == 1 and body["stream"] is False and body["model"] == "some/model"


@respx.mock
async def test_openai_list_models():
    respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
    )
    assert await build_client("groq", api_key=KEY).list_models() == ["a", "b"]


@respx.mock
async def test_list_models_best_effort_empty_on_error():
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(500))
    assert await build_client("openai", api_key=KEY).list_models() == []


# --- errors ----------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize(
    "status,kind,needle",
    [
        (401, "auth", "rejected the API key"),
        (403, "auth", "rejected the API key"),
        (404, "model", "model"),
        (429, "rate_limit", "rate limited"),
        (503, "provider", "503"),
    ],
)
async def test_http_errors_mapped(status, kind, needle):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(status, json={"error": {"message": f"bad {KEY}"}})
    )
    with pytest.raises(LLMError) as ei:
        await build_client("openai", api_key=KEY).test(model="m")
    err = ei.value
    assert err.kind == kind and err.status == status
    assert needle.lower() in err.message.lower()
    assert KEY not in err.message and KEY not in str(err)


@respx.mock
async def test_stream_error_before_first_chunk_raises():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "nope"}})
    )
    with pytest.raises(LLMError) as ei:
        await collect(
            build_client("openai", api_key=KEY).stream_chat(
                MSGS, model="m", temperature=0, max_tokens=5
            )
        )
    assert ei.value.kind == "auth"


@respx.mock
async def test_timeout_and_unreachable():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(LLMError) as ei:
        await build_client("openai", api_key=KEY).test(model="m")
    assert ei.value.kind == "timeout" and "timed out" in ei.value.message.lower()

    respx.post("http://127.0.0.1:11434/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError) as ei:
        await build_client("ollama", base_url="http://127.0.0.1:11434").test(model="m")
    assert ei.value.kind == "unreachable"
    assert "cannot reach ollama at http://127.0.0.1:11434" in ei.value.message.lower()


@respx.mock
async def test_provider_message_echoing_key_is_scrubbed():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": f"Invalid header: Bearer {KEY} for model zz"}}
        )
    )
    with pytest.raises(LLMError) as ei:
        await build_client("openai", api_key=KEY).test(model="zz")
    assert KEY not in ei.value.message
    assert "zz" in ei.value.message  # provider reason kept


# --- anthropic -------------------------------------------------------------------


@respx.mock
async def test_anthropic_stream_shape_and_sse():
    events = (
        'event: message_start\ndata: {"type":"message_start"}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi "}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there"}}\n\n'
        'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, content=events.encode())
    )
    client = build_client("anthropic", api_key=KEY)
    out = await collect(
        client.stream_chat(MSGS, model="claude-haiku-5-5", temperature=0.2, max_tokens=99)
    )
    assert out == "Hi there"
    req = route.calls.last.request
    assert req.headers["x-api-key"] == KEY and "anthropic-version" in req.headers
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body == {
        "model": "claude-haiku-5-5",
        "system": "be nice",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "temperature": 0.2,
        "max_tokens": 99,
    }


@respx.mock
async def test_anthropic_test_and_auth_error():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
    )
    with pytest.raises(LLMError) as ei:
        await build_client("anthropic", api_key=KEY).test(model="m")
    assert ei.value.kind == "auth" and "Anthropic" in ei.value.message


# --- ollama ----------------------------------------------------------------------


@respx.mock
async def test_ollama_stream_think_false_and_options():
    lines = (
        "\n".join(json.dumps({"message": {"content": c}}) for c in ["Hel", "lo"])
        + "\n"
        + json.dumps({"done": True})
    )
    route = respx.post("http://h:11434/api/chat").mock(
        return_value=httpx.Response(200, content=lines.encode())
    )
    client = build_client("ollama", base_url="http://h:11434")
    out = await collect(client.stream_chat(MSGS, model="gemma", temperature=0.5, max_tokens=70))
    assert out == "Hello"
    body = json.loads(route.calls.last.request.content)
    assert body["think"] is False and body["stream"] is True and body["model"] == "gemma"
    assert body["options"]["temperature"] == 0.5 and body["options"]["num_predict"] == 70


@respx.mock
async def test_ollama_list_models():
    respx.get("http://h:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "gemma:latest"}]})
    )
    assert await build_client("ollama", base_url="http://h:11434").list_models() == ["gemma"]
