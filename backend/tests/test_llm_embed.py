import json

import httpx
import pytest
import respx

from mebot.llm.base import LLMError
from mebot.llm.factory import build_client
from mebot.llm.providers import PROVIDERS, get_provider

KEY = "sk-test-SECRET-1234"


def test_registry_flags_embedding_support():
    supported = {p.id for p in PROVIDERS if p.embeddings}
    assert supported == {"openrouter", "gemini", "openai", "ollama", "openai_compatible"}
    for pid in ("openai", "openrouter", "gemini", "ollama"):
        assert get_provider(pid).default_embedding_model
    assert get_provider("anthropic").default_embedding_model is None
    assert get_provider("groq").embeddings is False


@pytest.mark.parametrize(
    ("provider", "base"),
    [
        ("openai", "https://api.openai.com/v1"),
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ],
)
async def test_openai_style_embed(provider, base):
    with respx.mock:
        route = respx.post(f"{base}/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={
                    # out of order on purpose: results are matched by index
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0]},
                        {"index": 0, "embedding": [1.0, 0.0]},
                    ],
                    "usage": {"prompt_tokens": 7, "total_tokens": 7},
                },
            )
        )
        client = build_client(provider, api_key=KEY)
        vecs = await client.embed(["a", "b"], model="emb-1")
    assert vecs == [[1.0, 0.0], [0.0, 1.0]]
    body = json.loads(route.calls[0].request.content)
    assert body == {"model": "emb-1", "input": ["a", "b"]}
    assert route.calls[0].request.headers["authorization"] == f"Bearer {KEY}"
    assert client.embed_tokens == 7


async def test_custom_openai_compatible_embed():
    with respx.mock:
        respx.post("http://llm.local/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5]}]})
        )
        client = build_client("openai_compatible", base_url="http://llm.local/v1")
        assert await client.embed(["x"], model="m") == [[0.5]]
        assert client.embed_tokens is None


async def test_ollama_embed():
    with respx.mock:
        route = respx.post("http://127.0.0.1:11434/api/embed").mock(
            return_value=httpx.Response(
                200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 5}
            )
        )
        client = build_client("ollama")
        assert await client.embed(["a", "b"], model="nomic-embed-text") == [[0.1, 0.2], [0.3, 0.4]]
    assert json.loads(route.calls[0].request.content) == {
        "model": "nomic-embed-text",
        "input": ["a", "b"],
    }
    assert client.embed_tokens == 5


@pytest.mark.parametrize("provider", ["anthropic", "groq"])
async def test_unsupported_providers_raise(provider):
    client = build_client(provider, api_key=KEY)
    with pytest.raises(LLMError) as e:
        await client.embed(["a"], model="m")
    assert e.value.kind == "unsupported"


async def test_embed_http_error_is_typed_and_scrubbed():
    with respx.mock:
        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})
        )
        client = build_client("openai", api_key=KEY)
        with pytest.raises(LLMError) as e:
            await client.embed(["a"], model="m")
    assert e.value.kind == "auth" and KEY not in e.value.message


async def test_embed_rejects_malformed_response():
    with respx.mock:
        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        )
        client = build_client("openai", api_key=KEY)
        with pytest.raises(LLMError) as e:
            await client.embed(["a", "b"], model="m")  # 2 inputs, 1 vector back
    assert e.value.kind == "bad_request"
