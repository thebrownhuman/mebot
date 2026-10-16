import logging

import pytest
from sqlalchemy import select

from mebot.imports.pipelines import Extracted, Item
from mebot.models import AccessLog, ImportJob
from tests.conftest import csrf
from tests.import_fixtures import (
    EXE,
    OLE_DOC,
    make_docm,
    make_docx,
    make_encrypted_pdf,
    make_pdf,
    make_zip,
)

RESUME_LINES = ["Jane Doe", "Backend Engineer at Acme", "2020 - 2023"]


class Spy:
    """Stands in for the real runners: records what it was given."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        self.fail: Exception | None = None

    def runner(self, kind):
        async def run(data: bytes, ctx):
            self.calls.append((ctx.filetype, len(data)))
            if self.fail:
                raise self.fail
            return Extracted(
                identity={"headline": "Backend Engineer"},
                sections={"skills": [Item(data={"name": "Python"})]},
                source_text="text" if kind == "resume" else None,
            )

        return run


@pytest.fixture
def spy(app):
    s = Spy()
    app.state.import_runners = {"resume": s.runner("resume"), "linkedin": s.runner("linkedin")}
    return s


def up(c, kind, data, name="cv.pdf"):
    return c.post(f"/api/admin/import/{kind}", files={"file": (name, data)}, headers=csrf(c))


def test_requires_auth_and_csrf(client, spy):
    from tests.conftest import do_setup

    do_setup(client)
    r = client.post("/api/admin/import/resume", files={"file": ("a.pdf", make_pdf(RESUME_LINES))})
    assert r.status_code == 403
    client.cookies.delete("mebot_session")
    assert up(client, "resume", make_pdf(RESUME_LINES)).status_code == 401


def test_unknown_kind_404(admin_client, spy):
    assert up(admin_client, "github", b"x").status_code == 404


def test_resume_pdf_processed_to_ready(admin_client, spy):
    r = up(admin_client, "resume", make_pdf(RESUME_LINES))
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    job = admin_client.get(f"/api/admin/import/jobs/{job_id}").json()
    assert job["status"] == "ready" and job["kind"] == "resume" and job["filename"] == "cv.pdf"
    assert job["draft"]["sections"]["skills"][0]["data"] == {"name": "Python"}
    assert job["source_text"] == "text"
    assert spy.calls == [("pdf", len(make_pdf(RESUME_LINES)))]


def test_docx_and_zip_accepted_per_kind(admin_client, spy):
    assert up(admin_client, "resume", make_docx(["Jane"]), "cv.docx").status_code == 202
    assert up(admin_client, "linkedin", make_zip({"Profile.csv": "a"}), "e.zip").status_code == 202
    assert [c[0] for c in spy.calls] == ["docx", "zip"]


@pytest.mark.parametrize(
    "kind,data,name,code",
    [
        ("resume", OLE_DOC, "cv.doc", "UNSUPPORTED_FILE"),
        ("resume", EXE, "cv.pdf", "UNSUPPORTED_FILE"),
        ("resume", b"hello world", "cv.pdf", "UNSUPPORTED_FILE"),
        ("resume", make_zip({"a.txt": "x"}), "cv.docx", "UNSUPPORTED_FILE"),
        ("linkedin", make_pdf(RESUME_LINES), "export.zip", "UNSUPPORTED_FILE"),
        ("linkedin", make_docx(["x"]), "export.zip", "UNSUPPORTED_FILE"),
    ],
    ids=["doc", "exe", "text", "zip-as-docx", "pdf-as-zip", "docx-as-zip"],
)
def test_magic_bytes_not_extension(admin_client, spy, kind, data, name, code):
    r = up(admin_client, kind, data, name)
    assert r.status_code == 415 and r.json()["error"]["code"] == code
    assert spy.calls == []


def test_macro_enabled_docx_rejected(admin_client, spy):
    r = up(admin_client, "resume", make_docm(["Jane"]), "cv.docx")
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_encrypted_pdf_rejected(admin_client, spy):
    r = up(admin_client, "resume", make_encrypted_pdf(RESUME_LINES))
    assert r.status_code == 415 and r.json()["error"]["code"] == "ENCRYPTED_PDF"


def test_size_limit(admin_client, spy, monkeypatch):
    from mebot.imports import pipelines

    monkeypatch.setitem(
        pipelines.KINDS, "resume", pipelines.Kind("resume", 2000, ("pdf", "docx"), True)
    )
    r = up(admin_client, "resume", b"%PDF-" + b"x" * 5000)
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    # within the header slack but over the limit once read
    r = up(admin_client, "resume", b"%PDF-" + b"x" * 2100)
    assert r.status_code == 413
    assert spy.calls == []


def test_missing_length_or_file(admin_client, spy):
    r = admin_client.post("/api/admin/import/resume", data={"x": "1"}, headers=csrf(admin_client))
    assert r.status_code == 422


def test_resume_needs_llm(admin_client, app, spy):
    from mebot.models import LLMConfig

    with app.state.session_factory() as db:
        db.query(LLMConfig).delete()
        db.commit()
    client = admin_client
    r = up(client, "resume", make_pdf(RESUME_LINES))
    assert r.status_code == 422 and r.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    assert (
        up(client, "linkedin", make_zip({"Skills.csv": "Name\nGo\n"}), "e.zip").status_code == 202
    )


def test_one_processing_job_at_a_time(admin_client, app, spy):
    from mebot.repos import bots, import_jobs

    with app.state.session_factory() as db:
        bot_id = bots.get_primary(db).id
        import_jobs.create(db, bot_id, "resume", filename="x", sha256="0" * 64, size=1)
        db.commit()
    r = up(admin_client, "linkedin", make_zip({"Skills.csv": "Name\nGo\n"}), "e.zip")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPORT_IN_PROGRESS"


def test_same_file_returns_existing_ready_job(admin_client, spy):
    pdf = make_pdf(RESUME_LINES)
    first = up(admin_client, "resume", pdf).json()["id"]
    r = up(admin_client, "resume", pdf)
    assert r.status_code == 200 and r.json()["id"] == first and r.json()["status"] == "ready"
    assert len(spy.calls) == 1


def test_rate_limit_10_per_hour(admin_client, spy):
    for i in range(10):
        assert up(admin_client, "resume", make_pdf([*RESUME_LINES, str(i)])).status_code == 202
    r = up(admin_client, "resume", make_pdf([*RESUME_LINES, "x"]))
    assert r.status_code == 429 and "retry-after" in r.headers


def test_runner_failure_and_crash_are_reported_without_content(admin_client, spy):
    from mebot.imports.filetype import ImportFailure

    spy.fail = ImportFailure("NO_TEXT", "Looks like a scanned PDF")
    job = up(admin_client, "resume", make_pdf(RESUME_LINES)).json()
    body = admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()
    assert body["status"] == "failed" and body["error_code"] == "NO_TEXT"
    spy.fail = RuntimeError("secret resume text Jane Doe")
    job = up(admin_client, "resume", make_pdf([*RESUME_LINES, "2"])).json()
    body = admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()
    assert body["error_code"] == "EXTRACTION_FAILED" and "Jane" not in body["error_message"]


def test_file_never_stored_or_logged(admin_client, app, spy, settings, caplog):
    before = sorted(p.name for p in settings.data_dir.rglob("*"))
    caplog.set_level(logging.DEBUG)
    up(admin_client, "resume", make_pdf(["UNIQUE-MARKER-4242", *RESUME_LINES]), "Jane CV.pdf")
    after = sorted(p.name for p in settings.data_dir.rglob("*"))
    assert [n for n in after if n not in before and not n.startswith("test.db")] == []
    assert "UNIQUE-MARKER-4242" not in caplog.text and "Jane CV" not in caplog.text
    with app.state.session_factory() as db:
        details = [a.detail or "" for a in db.scalars(select(AccessLog))]
        job = db.scalars(select(ImportJob)).one()
    assert not any("UNIQUE" in d or "Jane" in d for d in details)
    assert job.filename == "Jane CV.pdf"


def test_filename_sanitised(admin_client, spy):
    job = up(admin_client, "resume", make_pdf(RESUME_LINES), "../../etc/<x>.pdf").json()
    body = admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()
    assert body["filename"] == "_x_.pdf"


def test_list_and_discard(admin_client, spy):
    job_id = up(admin_client, "resume", make_pdf(RESUME_LINES)).json()["id"]
    items = admin_client.get("/api/admin/import/jobs").json()["items"]
    assert [i["id"] for i in items] == [job_id] and "draft" not in items[0]
    r = admin_client.delete(f"/api/admin/import/jobs/{job_id}", headers=csrf(admin_client))
    assert r.status_code == 204
    assert admin_client.get(f"/api/admin/import/jobs/{job_id}").status_code == 404
