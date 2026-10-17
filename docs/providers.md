# Add your API key

mebot never ships, provides or shares an API key. During setup (step 2 of 3) you
pick a provider, paste **your own** key, choose a model and press **Test**; setup
can't finish until that live test call succeeds. Change it later in
Admin → AI Provider (`/admin/llm`), which tests before saving.

| Provider | Where to get a key | Notes |
|---|---|---|
| Google Gemini | https://aistudio.google.com/apikey | Free tier available. Uses Gemini's OpenAI-compatible endpoint. |
| OpenAI | https://platform.openai.com/api-keys | |
| Anthropic | https://console.anthropic.com/settings/keys | |
| OpenRouter | https://openrouter.ai/keys | One key, many models (`vendor/model` ids). |
| Groq | https://console.groq.com/keys | |
| Ollama | no key | Runs locally; base URL defaults to `OLLAMA_HOST`. Pull a model first (`ollama pull gemma3`). |
| OpenAI-compatible | depends on the server | Any `/chat/completions` API (vLLM, LM Studio, LiteLLM proxy…); enter its base URL, key optional. |

The key is stored encrypted (Fernet, derived from `SECRET_KEY`) and is never sent
back to the browser — the admin page shows only its last 4 characters. If you change
`SECRET_KEY` the stored key can't be decrypted: chat pauses and the admin panel asks
you to re-enter it. When the provider fails (bad key, quota, outage) visitors see a
polite "assistant unavailable" message; the admin panel shows a banner and the access
log records `LLM_ERROR` with the provider and status code (never the key).

Upgrading an install from before this feature: log in, then follow the banner to
Admin → AI Provider; chat returns 503 until a provider is saved.

## Provider notes

**OpenRouter.** One key reaches models from many vendors; model ids look like
`anthropic/claude-sonnet-4.5` or `google/gemini-2.5-flash`. Set a monthly credit limit on the
key in the OpenRouter dashboard as a second guard next to Admin → Limits.

**Google Gemini.** Create a key in AI Studio. The free tier is rate-limited per minute; on a
busy day visitors may see "assistant unavailable" until the window resets. mebot calls
Gemini's OpenAI-compatible endpoint, so any Gemini chat model id works.

**OpenAI.** Create a project key; restrict it to the models you use and set a usage limit on
the project.

**Anthropic.** Create a key in the Console under a workspace with a spend limit. Use any
current Claude model id.

**Groq.** Fast, cheap open models (Llama, Qwen, …). The free tier has low daily token limits;
pair it with a token cap in Admin → Limits.

**Ollama.** No key and no per-message cost. Run Ollama on the host (`ollama serve`,
`ollama pull gemma3`) and keep the default base URL; the Docker compose file maps
`host.docker.internal` for you. Or run the bundled container: `docker compose --profile ollama
up -d`, then set the base URL to `http://ollama:11434` in Admin → AI Provider and pull a model
with `docker compose exec ollama ollama pull gemma3`. An example persona Modelfile is in
`deploy/ollama/`.

**OpenAI-compatible servers** (vLLM, LM Studio, LiteLLM, llama.cpp server, …). Enter the base
URL that serves `/chat/completions` (usually ending in `/v1`) and a key if the server needs
one. From inside Docker, `localhost` is the container itself: use `host.docker.internal`.

