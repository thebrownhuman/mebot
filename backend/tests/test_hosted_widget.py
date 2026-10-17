"""Hosted embeds address bots by public key, never by slug."""

from conftest import make_tenant
from fastapi.testclient import TestClient


def test_public_widget_by_public_key_only(tenants, hosted_app):
    a, b = tenants
    with TestClient(hosted_app) as anon:
        assert anon.get(f"/api/public/widget/{a.public_key}").status_code == 200
        assert anon.get(f"/api/public/widget/{a.slug}").status_code == 404
        assert anon.get("/api/public/widget/pk_nope").status_code == 404
        assert anon.get(f"/embed/{b.public_key}").status_code == 200
        assert anon.get(f"/embed/{b.slug}").status_code == 404
        cfg_a = anon.get(f"/api/public/widget/{a.public_key}").json()
    assert "Alice" in cfg_a["title"]


def test_not_live_bot_has_no_embed(hosted_app):
    t = make_tenant(hosted_app, "suspd", status="suspended")
    with TestClient(hosted_app) as anon:
        assert anon.get(f"/api/public/widget/{t.public_key}").status_code == 404


def test_snippets_and_test_page_use_public_key(tenants):
    a, _ = tenants
    snip = a.client.get("/api/admin/widget/snippets").json()
    assert f'data-bot="{a.public_key}"' in snip["script"]
    assert a.slug not in snip["script"]
    assert a.client.get("/api/admin/widget").json()["embed_ref"] == a.public_key
    page = a.client.get("/widget-test").text
    assert f'data-bot="{a.public_key}"' in page


def test_single_mode_embed_ref_is_slug(admin_client):
    assert admin_client.get("/api/admin/widget").json()["embed_ref"] == "shivansh"
