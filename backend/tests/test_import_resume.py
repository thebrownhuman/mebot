import json

import pytest

from mebot.imports import resume
from mebot.imports.filetype import ImportFailure
from tests.conftest import csrf
from tests.import_fixtures import make_docx, make_pdf

LINES = [
    "Jane Doe",
    "Senior Backend Engineer - Bengaluru",
    "Experience",
    "Acme Corp - Backend Engineer, Feb 2021 - Present",
    "Built payment APIs in Python and FastAPI serving 2M requests a day.",
    "Globex - Software Engineer Intern, 2019-06 to 2019-12",
    "Education",
    "IIT Bombay - B.Tech Computer Science, 2016 - 2020",
    "Skills: Python, FastAPI, PostgreSQL, Kubernetes",
    "Projects: mebot - a portfolio chatbot (github.com/jane/mebot)",
]

GOOD = {
    "identity": {
        "full_name": "Jane Doe",
        "headline": "Senior Backend Engineer",
        "location": "Bengaluru",
        "summary": None,
    },
    "experiences": [
        {
            "company": "Acme Corp",
            "title": "Backend Engineer",
            "start_month": "2021-02",
            "end_month": None,
            "description": "Built payment APIs in Python and FastAPI.",
            "tech": ["Python", "FastAPI"],
        },
        {
            "company": "Globex",
            "title": "Software Engineer Intern",
            "employment_type": "internship",
            "start_month": "2019-06",
            "end_month": "2019-12",
        },
    ],
    "educations": [
        {
            "institution": "IIT Bombay",
            "degree": "B.Tech",
            "field": "Computer Science",
            "start_month": "2016-01",
            "end_month": "2020-01",
        }
    ],
    "skills": [{"name": "Python", "category": "language"}, {"name": "PostgreSQL"}],
    "projects": [{"name": "mebot", "summary": "a portfolio chatbot", "tech": []}],
    "interests": [],
    "channels": [
        {"kind": "github", "value": "https://github.com/jane/mebot"},
        {"kind": "phone", "value": "+91 98765 43210"},
    ],
}


def resume_text():
    return "\n".join(LINES) + "\n" + "Filler line for length. " * 10


def test_pdf_and_docx_text():
    pdf = resume.extract_text(make_pdf([*LINES, "x" * 60]), "pdf")
    assert "Acme Corp - Backend Engineer" in pdf and "IIT Bombay" in pdf
    docx = resume.extract_text(
        make_docx([*LINES], table=[["Python", "FastAPI"], ["Go", "Go"]]), "docx"
    )
    assert "Skills: Python" in docx and "Python | FastAPI" in docx
    assert "Go | Go" not in docx  # merged cells collapse


def test_too_little_text_is_no_text():
    with pytest.raises(ImportFailure) as e:
        resume.extract_text(make_pdf(["Jane"]), "pdf")
    assert e.value.code == "NO_TEXT" and "scanned" in e.value.message


def test_chunking_at_headings():
    body = "\n".join(
        [f"{h}\n" + "\n".join(f"{h} line {i} " + "y" * 80 for i in range(70)) for h in
         ("Experience", "Education", "Projects")]
    )  # fmt: skip
    parts = resume.chunks(body, size=12_000)
    assert len(parts) >= 2 and all(len(p) <= 12_000 for p in parts)
    assert parts[1].lstrip().split("\n")[0] in ("Education", "Projects")
    assert resume.chunks("short text") == ["short text"]


def test_merge_dedupes_and_keeps_first_identity():
    a = resume.parse(json.dumps({"identity": {"full_name": "Jane"}, "skills": [{"name": "Go"}]}))
    b = resume.parse(json.dumps({"identity": {"full_name": "X", "headline": "Eng"},
                                 "skills": [{"name": "go"}, {"name": "Rust"}]}))  # fmt: skip
    m = resume.merge([a, b])
    assert m.identity.full_name == "Jane" and m.identity.headline == "Eng"
    assert [s.name for s in m.skills] == ["Go", "Rust"]


def test_parse_tolerates_fences_and_junk():
    out = resume.parse('```json\n{"skills": [{"name": 5}, "x"], "experiences": null}\n```')
    assert [s.name for s in out.skills] == ["5"] and out.experiences == []
    with pytest.raises(ValueError):
        resume.parse("sorry, I can't")


# --- through the API ---------------------------------------------------------------------


def upload(c, data, name="cv.pdf"):
    r = c.post("/api/admin/import/resume", files={"file": (name, data)}, headers=csrf(c))
    assert r.status_code == 202, r.text
    return c.get(f"/api/admin/import/jobs/{r.json()['id']}").json()


def test_resume_to_draft(admin_client, fake_llm):
    fake_llm.replies = [json.dumps(GOOD)]
    job = upload(admin_client, make_docx(resume_text().splitlines()), "cv.docx")
    assert job["status"] == "ready", job
    sec = job["draft"]["sections"]
    assert {i["data"]["field"]: i["data"]["value"] for i in sec["identity"]}[
        "full_name"
    ] == "Jane Doe"
    exp = sec["experiences"][0]["data"]
    assert exp["company"] == "Acme Corp" and exp["start_month"] == "2021-02"
    assert "end_month" not in exp
    assert [s["data"]["name"] for s in sec["skills"]] == ["Python", "PostgreSQL"]
    assert [c["data"]["kind"] for c in sec["links"]] == ["github"]  # phone never
    assert job["source_text"].startswith("Jane Doe")
    # the prompt carried the resume as data and the rules
    msgs = fake_llm.streams[-1]["messages"]
    assert "Extract ONLY what is written" in msgs[0]["content"]
    assert msgs[1]["content"].startswith("<resume>") and "Acme Corp" in msgs[1]["content"]
    assert fake_llm.streams[-1]["temperature"] == 0.0


def test_invalid_json_repaired_once(admin_client, fake_llm):
    fake_llm.replies = ["Here you go: {not json", json.dumps(GOOD)]
    job = upload(admin_client, make_docx(resume_text().splitlines()), "cv.docx")
    assert job["status"] == "ready"
    assert "not valid JSON" in fake_llm.streams[-1]["messages"][-1]["content"]


def test_invalid_twice_fails(admin_client, fake_llm):
    fake_llm.replies = ["nope", "still nope"]
    job = upload(admin_client, make_docx(resume_text().splitlines()), "cv.docx")
    assert job["status"] == "failed" and job["error_code"] == "EXTRACTION_FAILED"
    assert job["draft"] is None


def test_provider_error_fails_without_partial_draft(admin_client, fake_llm):
    from mebot.llm.base import LLMError

    fake_llm.replies = [LLMError("timeout", "timed out")]
    job = upload(admin_client, make_docx(resume_text().splitlines()), "cv.docx")
    assert job["status"] == "failed" and job["draft"] is None


def test_timeout_fails(admin_client, fake_llm, monkeypatch):
    import asyncio

    from mebot.imports import pipelines

    async def slow(data, ctx):
        await asyncio.sleep(5)

    monkeypatch.setattr(pipelines, "TIMEOUT_SECONDS", 0.05)
    admin_client.app.state.import_runners = {"resume": slow}
    job = upload(admin_client, make_docx(resume_text().splitlines()), "cv.docx")
    assert job["status"] == "failed" and job["error_code"] == "EXTRACTION_FAILED"
    assert "too long" in job["error_message"]


def test_long_resume_extracted_per_chunk(admin_client, fake_llm):
    long_lines = []
    for h in ("Experience", "Education", "Projects"):
        long_lines.append(h)
        long_lines += [f"{h} detail {i} " + "z" * 90 for i in range(60)]
    fake_llm.replies = [json.dumps({"skills": [{"name": f"S{i}"}]}) for i in range(5)]
    job = upload(admin_client, make_docx(long_lines), "cv.docx")
    assert job["status"] == "ready"
    calls = len(fake_llm.streams)
    assert calls >= 2
    assert len(job["draft"]["sections"]["skills"]) == calls
