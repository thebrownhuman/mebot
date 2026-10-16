from sqlalchemy import select

from mebot.imports.pipelines import Extracted
from mebot.models import AccessLog, IntegrationToken
from tests.conftest import csrf

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def put(c, token):
    return c.put("/api/admin/integrations/github", json={"token": token}, headers=csrf(c))


def test_save_masked_encrypted_and_delete(admin_client, app):
    assert admin_client.get("/api/admin/integrations/github").json() == {
        "configured": False,
        "token_last4": None,
        "env_token": False,
    }
    r = put(admin_client, TOKEN)
    assert r.status_code == 200 and r.json()["token_last4"] == "6789"
    assert TOKEN not in r.text
    with app.state.session_factory() as db:
        row = db.scalars(select(IntegrationToken)).one()
        logs = " ".join(a.detail or "" for a in db.scalars(select(AccessLog)))
    assert TOKEN not in row.token_encrypted and TOKEN not in logs
    assert TOKEN not in admin_client.get("/api/admin/integrations/github").text
    r = admin_client.delete("/api/admin/integrations/github", headers=csrf(admin_client))
    assert r.status_code == 204
    assert admin_client.get("/api/admin/integrations/github").json()["configured"] is False


def test_validation_and_auth(admin_client):
    r = put(admin_client, "not a token!")
    assert r.status_code == 422
    r = admin_client.put("/api/admin/integrations/github", json={"token": TOKEN})
    assert r.status_code == 403


def test_saved_token_preferred_over_env(admin_client, app):
    seen = {}

    async def run(data, ctx):
        seen["token"] = ctx.options["token"]
        return Extracted()

    app.state.import_runners = {**app.state.import_runners, "github": run}
    app.state.settings.github_token = "ghp_ENV_ENV_ENV_ENV_ENV_ENV"
    post = lambda: admin_client.post(  # noqa: E731
        "/api/admin/import/github",
        json={"repo_urls": ["https://github.com/a/b"]},
        headers=csrf(admin_client),
    )
    post()
    assert seen["token"] == "ghp_ENV_ENV_ENV_ENV_ENV_ENV"
    put(admin_client, TOKEN)
    post()
    assert seen["token"] == TOKEN
    assert admin_client.get("/api/admin/integrations/github").json()["env_token"] is True
