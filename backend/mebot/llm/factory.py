from mebot.llm.anthropic import AnthropicClient
from mebot.llm.base import HttpAdapter
from mebot.llm.ollama import OllamaClient
from mebot.llm.openai_compat import OpenAICompatClient
from mebot.llm.providers import get_provider

_ADAPTERS = {"openai": OpenAICompatClient, "anthropic": AnthropicClient, "ollama": OllamaClient}


def build_client(
    provider_id: str, *, api_key: str | None = None, base_url: str | None = None
) -> HttpAdapter:
    provider = get_provider(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider {provider_id!r}")
    url = base_url or provider.default_base_url
    if not url:
        raise ValueError(f"{provider.name} needs a base URL")
    client = _ADAPTERS[provider.adapter](provider.name, url, api_key)
    if provider.id == "openai_compatible":
        client.include_usage = False
    return client
