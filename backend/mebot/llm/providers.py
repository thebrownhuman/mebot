"""Static provider registry. The project ships no API keys: owners bring their own."""

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    adapter: Literal["openai", "anthropic", "ollama"]
    key_required: bool
    default_base_url: str | None
    key_url: str | None
    suggested_models: tuple[str, ...] = field(default=())
    base_url_required: bool = False
    # Whether the adapter can call an embeddings endpoint (optional retrieval ranking).
    embeddings: bool = False
    default_embedding_model: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d.pop("adapter")
        d["suggested_models"] = list(self.suggested_models)
        return d


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "openrouter",
        "OpenRouter",
        "openai",
        True,
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/keys",
        ("google/gemini-2.5-flash", "openai/gpt-4o-mini", "meta-llama/llama-3.3-70b-instruct"),
        embeddings=True,
        default_embedding_model="openai/text-embedding-3-small",
    ),
    Provider(
        "gemini",
        "Google Gemini",
        "openai",
        True,
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "https://aistudio.google.com/apikey",
        ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"),
        embeddings=True,
        default_embedding_model="gemini-embedding-001",
    ),
    Provider(
        "openai",
        "OpenAI",
        "openai",
        True,
        "https://api.openai.com/v1",
        "https://platform.openai.com/api-keys",
        ("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"),
        embeddings=True,
        default_embedding_model="text-embedding-3-small",
    ),
    Provider(
        "anthropic",
        "Anthropic",
        "anthropic",
        True,
        "https://api.anthropic.com",
        "https://console.anthropic.com/settings/keys",
        ("claude-haiku-5-5", "claude-sonnet-5-5"),
    ),
    Provider(
        "groq",
        "Groq",
        "openai",
        True,
        "https://api.groq.com/openai/v1",
        "https://console.groq.com/keys",
        ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
    ),
    Provider(
        "ollama",
        "Ollama",
        "ollama",
        False,
        "http://127.0.0.1:11434",
        None,
        ("gemma3", "llama3.2"),
        embeddings=True,
        default_embedding_model="nomic-embed-text",
    ),
    Provider(
        "openai_compatible",
        "OpenAI-compatible (custom URL)",
        "openai",
        False,
        None,
        None,
        (),
        base_url_required=True,
        embeddings=True,
    ),
)

_BY_ID = {p.id: p for p in PROVIDERS}


def get_provider(provider_id: str) -> Provider | None:
    return _BY_ID.get(provider_id)
