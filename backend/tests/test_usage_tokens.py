import json

import httpx
import respx
from sqlalchemy import select

from mebot.llm.base import Usage
from mebot.llm.factory import build_client
from mebot.models import UsageCounter
from tests.test_chat_limits import chat, new_session, set_limits
from tests.test_llm_adapters import KEY, MSGS, collect, openai_chunk, sse

# --- adapters report provider usage --------------------------------------------------


@respx.mock
async def test_openai_requests_and_reads_usage():
    usage_chunk = json.dumps(
        {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 7}}
    )
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=sse(openai_chunk("Hi"), usage_chunk, "[DONE]"))
    )
    client = build_client("openai", api_key=KEY)
    assert client.usage is None
    out = await collect(client.stream_chat(MSGS, model="m", temperature=0, max_tokens=5))
    assert out == "Hi"
    assert json.loads(route.calls.last.request.content)["stream_options"] == {"include_usage": True}
    assert client.usage == Usage(prompt_tokens=120, completion_tokens=7)


@respx.mock
async def test_custom_openai_compatible_does_not_send_stream_options():
    route = respx.post("http://llm.local:9000/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=sse(openai_chunk("x"), "[DONE]"))
    )
    client = build_client("openai_compatible", base_url="http://llm.local:9000/v1")
    await collect(client.stream_chat(MSGS, model="m", temperature=0, max_tokens=5))
    assert "stream_options" not in json.loads(route.calls.last.request.content)
    assert client.usage is None


@respx.mock
async def test_anthropic_usage_from_message_events():
    events = (
        'data: {"type":"message_start",'
        '"message":{"usage":{"input_tokens":200,"output_tokens":1}}}\n\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
        'data: {"type":"message_delta","usage":{"output_tokens":15}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, content=events.encode())
    )
    client = build_client("anthropic", api_key=KEY)
    assert await collect(client.stream_chat(MSGS, model="m", temperature=0, max_tokens=5)) == "Hi"
    assert client.usage == Usage(prompt_tokens=200, completion_tokens=15)


@respx.mock
async def test_ollama_usage_from_final_line():
    lines = "\n".join(
        [
            json.dumps({"message": {"content": "Hi"}}),
            json.dumps({"done": True, "prompt_eval_count": 50, "eval_count": 9}),
        ]
    )
    respx.post("http://h:11434/api/chat").mock(
        return_value=httpx.Response(200, content=lines.encode())
    )
    client = build_client("ollama", base_url="http://h:11434")
    await collect(client.stream_chat(MSGS, model="m", temperature=0, max_tokens=5))
    assert client.usage == Usage(prompt_tokens=50, completion_tokens=9)


# --- chat route: counters, estimate, cap, history -----------------------------------


def _counter(app, scope):
    with app.state.session_factory() as db:
        return db.scalar(select(UsageCounter).where(UsageCounter.scope == scope))


def test_reported_usage_added_to_counters(admin_client, app, fake_llm):
    fake_llm.usage = Usage(prompt_tokens=300, completion_tokens=20)
    sid = new_session(admin_client)
    chat(admin_client, sid)
    for scope in ("bot_day", "ip_day"):
        row = _counter(app, scope)
        assert (row.messages, row.tokens, row.estimated_tokens) == (1, 320, 0)


def test_estimated_usage_when_provider_silent(admin_client, app, fake_llm):
    sid = new_session(admin_client)
    chat(admin_client, sid)
    call = fake_llm.streams[-1]
    prompt_chars = sum(len(m["content"]) for m in call["messages"])
    expected = -(-prompt_chars // 4) + -(-len("Hello there") // 4)
    row = _counter(app, "bot_day")
    assert row.tokens == expected and row.estimated_tokens == expected


def test_daily_token_cap_blocks_next_chat(admin_client, app, fake_llm):
    fake_llm.usage = Usage(prompt_tokens=90, completion_tokens=10)
    set_limits(app, daily_token_cap=100)
    sid = new_session(admin_client)
    assert chat(admin_client, sid).status_code == 200
    r = chat(admin_client, sid)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "DAILY_CAP_REACHED"
    assert r.json()["error"]["details"] == [{"field": "scope", "message": "bot_tokens"}]
    assert len(fake_llm.streams) == 1


def test_history_trimmed_to_n_turns(admin_client, app, fake_llm):
    set_limits(app, history_turns=2)
    sid = new_session(admin_client)
    for i in range(4):
        chat(admin_client, sid, f"q{i}")
    sent = fake_llm.streams[-1]["messages"]
    assert sent[0]["role"] == "system"
    # system + last 2 stored messages (q2, its answer) + the new question
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert "q2" in sent[1]["content"] and "q3" in sent[-1]["content"]
