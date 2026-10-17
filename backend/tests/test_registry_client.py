import json
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from mebot.telemetry import identity, semver
from mebot.telemetry.client import MAX_RESPONSE_BYTES, RegistryClient, RegistryError

VECTORS = json.loads((Path(__file__).parent / "registry_vectors.json").read_text("utf-8"))
BASE = "https://registry.example.test"
KEY = identity.from_seed_hex(VECTORS["private_seed_hex"])
NOW = 1760700000


def client(base=BASE, **kw) -> RegistryClient:
    return RegistryClient(base, KEY, "0.9.0", "single", **kw)


def latest_body(**over) -> dict:
    return {
        "latest": "0.10.1",
        "min_supported": "0.8.0",
        "released_at": "2026-10-10",
        "notes_url": "https://example.com/notes",
        "advisories": [
            {
                "id": "A-1",
                "severity": "high",
                "affected": "<0.10.1",
                "title": "Fix",
                "url": "https://example.com/a",
            }
        ],
        **over,
    }


def verify(request: httpx.Request) -> None:
    """The signature on an outgoing request verifies against the install's public key."""
    ts = request.headers["x-mebot-timestamp"]
    msg = identity.canonical(request.method, request.url.path, ts, request.content)
    import base64

    Ed25519PublicKey.from_public_bytes(KEY.public_raw).verify(
        base64.b64decode(request.headers["x-mebot-signature"]), msg
    )
    assert request.headers["x-mebot-install"] == KEY.install_id


class TestSemver:
    @pytest.mark.parametrize(
        ("latest", "current", "expected"),
        [
            ("0.10.1", "0.9.0", True),
            ("0.9.1", "0.9.0", True),
            ("1.0.0", "0.99.9", True),
            ("0.9.0", "0.9.0", False),
            ("0.8.0", "0.9.0", False),
            ("0.9.0", "0.9.0-dev", False),  # a dev build is not behind its own release
            ("0.9.1", "0.9.0-dev", True),
            ("0.10.0", "0.9.0+local", True),
            ("garbage", "0.9.0", False),
            ("0.9.0", "garbage", False),
            (None, "0.9.0", False),
        ],
    )
    def test_update_available(self, latest, current, expected):
        assert semver.update_available(latest, current) is expected

    @pytest.mark.parametrize(
        ("spec", "current", "expected"),
        [
            ("<0.10.1", "0.9.0", True),
            ("<0.10.1", "0.10.1", False),
            ("<=0.10.1", "0.10.1", True),
            (">=0.9.0,<0.10.1", "0.9.5", True),
            (">=0.9.0,<0.10.1", "0.8.9", False),
            (">=0.9.0, <0.10.1", "0.10.1", False),
            ("==0.9.0", "0.9.0", True),
            ("<0.10.1", "0.9.0-dev", True),
            ("<banana", "0.9.0", False),
            ("", "0.9.0", False),
            ("0.9.0", "0.9.0", False),
            ("<0.10.1", "dev", False),
        ],
    )
    def test_affected(self, spec, current, expected):
        assert semver.affected(spec, current) is expected

    def test_major(self):
        assert semver.major("1.2.3") == 1 and semver.major("v0.9.0") == 0
        assert semver.major("x") is None


@pytest.mark.asyncio
class TestRequests:
    @respx.mock
    async def test_heartbeat_sends_exactly_four_fields_signed(self):
        route = respx.post(f"{BASE}/v1/heartbeat").mock(return_value=httpx.Response(204))
        payload = await client().heartbeat(NOW)
        req = route.calls[0].request
        sent = json.loads(req.content)
        assert (
            sent
            == payload
            == {
                "install_id": KEY.install_id,
                "public_key": KEY.public_b64,
                "version": "0.9.0",
                "mode": "single",
            }
        )
        assert req.headers["x-mebot-timestamp"] == str(NOW)
        verify(req)

    @respx.mock
    async def test_heartbeat_matches_the_shared_vector_signature(self):
        case = VECTORS["cases"][0]
        route = respx.post(f"{BASE}/v1/heartbeat").mock(return_value=httpx.Response(204))
        await client().heartbeat(int(case["timestamp"]))
        assert route.calls[0].request.content.decode() == case["body"]
        assert route.calls[0].request.headers["x-mebot-signature"] == case["signature_b64"]

    @respx.mock
    async def test_register_sends_email_and_site_and_nothing_else(self):
        route = respx.post(f"{BASE}/v1/register").mock(return_value=httpx.Response(201, json={}))
        await client().register("priya@acme.dev", "https://priya.dev", NOW)
        req = route.calls[0].request
        assert json.loads(req.content) == {
            "install_id": KEY.install_id,
            "public_key": KEY.public_b64,
            "version": "0.9.0",
            "email": "priya@acme.dev",
            "site_url": "https://priya.dev",
        }
        verify(req)

    @respx.mock
    async def test_unregister_is_a_signed_delete_without_a_body(self):
        route = respx.delete(f"{BASE}/v1/register").mock(return_value=httpx.Response(204))
        await client().unregister(int(VECTORS["cases"][2]["timestamp"]))
        req = route.calls[0].request
        assert req.content == b""
        assert req.headers["x-mebot-signature"] == VECTORS["cases"][2]["signature_b64"]

    @respx.mock
    async def test_latest_is_public_and_unsigned(self):
        route = respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(200, json=latest_body())
        )
        info = await client().latest()
        assert "x-mebot-signature" not in route.calls[0].request.headers
        assert info.latest == "0.10.1" and info.advisories[0].affected == "<0.10.1"

    @respx.mock
    async def test_base_url_trailing_slash_and_path_prefix(self):
        route = respx.get("http://localhost:8100/v1/latest").mock(
            return_value=httpx.Response(200, json=latest_body())
        )
        await client("http://localhost:8100/").latest()
        assert route.called


@pytest.mark.asyncio
class TestOutboundSafety:
    @respx.mock
    async def test_redirects_are_never_followed(self):
        other = respx.get("https://evil.example/v1/latest").mock(
            return_value=httpx.Response(200, json=latest_body())
        )
        respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(302, headers={"Location": "https://evil.example/v1/latest"})
        )
        with pytest.raises(RegistryError) as e:
            await client().latest()
        assert e.value.kind == "redirect" and not other.called

    @respx.mock
    async def test_a_redirected_heartbeat_is_not_replayed_elsewhere(self):
        other = respx.post("https://evil.example/v1/heartbeat").mock(
            return_value=httpx.Response(204)
        )
        respx.post(f"{BASE}/v1/heartbeat").mock(
            return_value=httpx.Response(
                307, headers={"Location": "https://evil.example/v1/heartbeat"}
            )
        )
        with pytest.raises(RegistryError):
            await client().heartbeat(NOW)
        assert not other.called

    @respx.mock
    async def test_only_the_registry_host_is_contacted(self):
        respx.post(f"{BASE}/v1/heartbeat").mock(return_value=httpx.Response(204))
        respx.get(f"{BASE}/v1/latest").mock(return_value=httpx.Response(200, json=latest_body()))
        c = client()
        await c.heartbeat(NOW)
        await c.latest()
        assert {call.request.url.host for call in respx.calls} == {"registry.example.test"}

    @respx.mock
    async def test_oversized_response_is_refused(self):
        respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(
                200, content=b'{"latest":"1.0.0","pad":"' + b"x" * MAX_RESPONSE_BYTES + b'"}'
            )
        )
        with pytest.raises(RegistryError) as e:
            await client().latest()
        assert e.value.kind == "too_large"

    @respx.mock
    async def test_response_just_under_the_cap_is_accepted(self):
        pad = "x" * (MAX_RESPONSE_BYTES - 200)
        respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(200, json={"latest": "1.0.0", "pad": pad})
        )
        assert (await client().latest()).latest == "1.0.0"

    @respx.mock
    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"[]",
            b"{}",
            json.dumps({"latest": "banana"}).encode(),
            json.dumps({"latest": 5}).encode(),
            json.dumps(latest_body(advisories="nope")).encode(),
            json.dumps(latest_body(advisories=[{"id": "x"}])).encode(),
            json.dumps(
                latest_body(advisories=[{"id": "x", "affected": "<1", "title": "t"}] * 51)
            ).encode(),
            json.dumps(latest_body(latest="9" * 50)).encode(),
        ],
    )
    async def test_malformed_latest_is_a_schema_error(self, body):
        respx.get(f"{BASE}/v1/latest").mock(return_value=httpx.Response(200, content=body))
        with pytest.raises(RegistryError) as e:
            await client().latest()
        assert e.value.kind == "schema"

    @respx.mock
    async def test_non_http_links_are_dropped(self):
        body = latest_body(
            notes_url="javascript:alert(1)",
            advisories=[
                {"id": "a", "affected": "<1.0.0", "title": "t", "url": "javascript:alert(1)"},
                {"id": "b", "affected": "<1.0.0", "title": "t", "url": "https://ok.example/x"},
                {"id": "c", "affected": "<1.0.0", "title": "t", "url": "data:text/html,x"},
            ],
        )
        respx.get(f"{BASE}/v1/latest").mock(return_value=httpx.Response(200, json=body))
        info = await client().latest()
        assert info.notes_url is None
        assert [a.url for a in info.advisories] == [None, "https://ok.example/x", None]

    @respx.mock
    async def test_unknown_fields_are_ignored(self):
        respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(200, json=latest_body(surprise={"a": 1}))
        )
        assert (await client().latest()).latest == "0.10.1"

    @respx.mock
    async def test_invalid_min_supported_is_dropped_not_fatal(self):
        respx.get(f"{BASE}/v1/latest").mock(
            return_value=httpx.Response(200, json=latest_body(min_supported="soon"))
        )
        assert (await client().latest()).min_supported is None


@pytest.mark.asyncio
class TestErrors:
    @respx.mock
    @pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
    async def test_http_errors_carry_status_and_code(self, status):
        respx.post(f"{BASE}/v1/heartbeat").mock(
            return_value=httpx.Response(
                status, json={"error": {"code": "NOPE", "message": "m", "status": status}}
            )
        )
        with pytest.raises(RegistryError) as e:
            await client().heartbeat(NOW)
        assert (e.value.kind, e.value.status) == ("http", status) and "NOPE" in str(e.value)

    @respx.mock
    async def test_non_json_error_body(self):
        respx.post(f"{BASE}/v1/heartbeat").mock(return_value=httpx.Response(502, text="<html>"))
        with pytest.raises(RegistryError) as e:
            await client().heartbeat(NOW)
        assert e.value.kind == "http" and e.value.status == 502

    @respx.mock
    @pytest.mark.parametrize(
        "exc", [httpx.ConnectError("dns"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow")]
    )
    async def test_network_failures(self, exc):
        respx.post(f"{BASE}/v1/heartbeat").mock(side_effect=exc)
        with pytest.raises(RegistryError) as e:
            await client().heartbeat(NOW)
        assert e.value.kind == "network"

    async def test_timeout_is_five_seconds(self):
        from mebot.telemetry import client as mod

        assert mod.TIMEOUT_SECONDS == 5.0
