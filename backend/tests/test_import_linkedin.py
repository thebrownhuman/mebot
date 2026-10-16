import zipfile

import pytest

from mebot.imports import linkedin
from mebot.imports.filetype import ImportFailure
from tests.conftest import csrf
from tests.import_fixtures import make_zip

BOM = "\ufeff"

PROFILE = (
    BOM + "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,"
    "Zip Code,Geo Location\n"
    'Jane,Doe,,"12 Secret St",1 Jan 1995,Backend Engineer,"Builds APIs.",Software,560001,'
    '"Bengaluru, India"\n'
)
POSITIONS = (
    "Company Name,Title,Description,Location,Started On,Finished On\n"
    'Acme,Backend Engineer,"Payments APIs",Bengaluru,Feb 2021,\n'
    "Globex,Intern,,Pune,2019,2019\n"
)
EDUCATION = (
    "Notes:\n"
    '"This file lists your schools."\n'
    "\n"
    "School Name,Start Date,End Date,Notes,Degree Name,Activities\n"
    'IIT Bombay,2016,2020,,"B.Tech, Computer Science",\n'
)
SKILLS = "name\nPython\nPostgreSQL\n"
PROJECTS = (
    "Title,Description,Url,Started On,Finished On\nmebot,Portfolio bot,https://x.dev,Jan 2024,\n"
)
CERTS = "Name,Url,Authority,Started On,Finished On,License Number\nCKA,,CNCF,Mar 2023,,123\n"
LANGS = "Name,Proficiency\nHindi,Native or bilingual proficiency\n"
HONORS = "Title,Description,Issued On\nHackathon winner,Best AI hack,Nov 2022\n"
EMAILS = (
    "Email Address,Confirmed,Primary,Updated On\n"
    "jane@work.dev,Yes,No,1/1/24\njane@home.dev,Yes,Yes,1/1/24\n"
)


def export(**over):
    files = {
        "Profile.csv": PROFILE,
        "Positions.csv": POSITIONS,
        "Education.csv": EDUCATION,
        "Skills.csv": SKILLS,
        "Projects.csv": PROJECTS,
        "Certifications.csv": CERTS,
        "Languages.csv": LANGS,
        "Honors.csv": HONORS,
        "Email Addresses.csv": EMAILS,
        "messages.csv": "FROM,TO,CONTENT\nBob,Jane,secret message\n",
        "Connections.csv": "First Name,Last Name\nBob,Smith\n",
        "PhoneNumbers.csv": "Number\n+91 98765 43210\n",
    }
    files.update(over)
    return make_zip({k: v for k, v in files.items() if v is not None})


@pytest.mark.parametrize(
    "raw,want",
    [
        ("Jan 2020", ("2020-01", False)),
        ("January 2020", ("2020-01", False)),
        ("Sept 2021", ("2021-09", False)),
        ("2020", ("2020-01", True)),
        ("2020-03", ("2020-03", False)),
        ("2020-3-15", ("2020-03", False)),
        ("03/2020", ("2020-03", False)),
        ("15 Mar 2020", ("2020-03", False)),
        ("", (None, False)),
        ("someday", (None, False)),
        ("13/2020", (None, False)),
    ],
)
def test_date_table(raw, want):
    assert linkedin.parse_date(raw) == want


def test_csv_bom_preamble_and_header_variants():
    rs = linkedin.rows(EDUCATION, linkedin.H["education"])
    assert rs[0]["schoolname"] == "IIT Bombay" and rs[0]["degreename"] == "B.Tech, Computer Science"
    rs = linkedin.rows(
        BOM + "COMPANY  NAME,title,STARTED ON\nAcme,Eng,2020\n", linkedin.H["positions"]
    )
    assert rs == [{"companyname": "Acme", "title": "Eng", "startedon": "2020"}]
    assert linkedin.rows("nothing useful\n", linkedin.H["skills"]) == []


def test_full_mapping():
    ex = linkedin.parse(export())
    assert ex.identity == {
        "full_name": "Jane Doe",
        "headline": "Backend Engineer",
        "summary": "Builds APIs.",
        "location": "Bengaluru, India",
    }
    exps = ex.sections["experiences"]
    assert exps[0].data == {
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Bengaluru",
        "description": "Payments APIs",
        "start_month": "2021-02",
    }  # empty Finished On -> current role
    assert not exps[0].needs_review
    assert exps[1].needs_review and "Only the year" in exps[1].reason
    edu = ex.sections["educations"]
    assert edu[0].data["degree"] == "B.Tech" and edu[0].data["field"] == "Computer Science"
    cert = [e for e in edu if e.kind == "certification"][0]
    assert cert.data == {"institution": "CNCF", "degree": "CKA", "start_month": "2023-03"}
    skills = {s.data["name"]: s.data for s in ex.sections["skills"]}
    assert skills["Hindi"]["category"] == "language" and "Python" in skills
    assert ex.sections["projects"][0].data["live_url"] == "https://x.dev"
    assert "Hackathon winner (Nov 2022): Best AI hack" in ex.sections["notes"][0].data["content"]
    emails = ex.sections["links"]
    assert [(e.data["value"], e.default_skip) for e in emails] == [
        ("jane@work.dev", True),
        ("jane@home.dev", False),
    ]
    flat = repr(ex)
    for secret in ("12 Secret St", "1 Jan 1995", "560001", "secret message", "Bob", "98765"):
        assert secret not in flat


def test_nested_and_case_insensitive_names():
    data = make_zip({"Basic_LinkedInDataExport/sub/SKILLS.CSV": SKILLS})
    assert [s.data["name"] for s in linkedin.parse(data).sections["skills"]] == [
        "Python",
        "PostgreSQL",
    ]


def test_only_allow_listed_entries_are_opened(monkeypatch):
    opened = []
    real = zipfile.ZipFile.open

    def spy(self, name, *a, **kw):
        opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return real(self, name, *a, **kw)

    data = export()  # built before spying: writing a zip opens entries too
    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    linkedin.parse(data)
    assert opened and all(n.rsplit("/", 1)[-1] in {
        "Profile.csv", "Positions.csv", "Education.csv", "Skills.csv", "Projects.csv",
        "Certifications.csv", "Languages.csv", "Honors.csv", "Email Addresses.csv",
    } for n in opened)  # fmt: skip
    assert not any("messages" in n.lower() or "connections" in n.lower() or "phone" in n.lower()
                   for n in opened)  # fmt: skip


def test_no_linkedin_files():
    with pytest.raises(ImportFailure) as e:
        linkedin.parse(make_zip({"messages.csv": "a,b\n1,2\n"}))
    assert e.value.code == "NO_LINKEDIN_FILES"


@pytest.mark.parametrize(
    "files",
    [
        {"../evil.csv": "x"},
        {"/abs/Skills.csv": "x"},
        {"C:/win/Skills.csv": "x"},
        {f"f{i}.txt": "" for i in range(1001)},
    ],
    ids=["dotdot", "absolute", "drive", "too-many"],
)
def test_unsafe_zips(files):
    with pytest.raises(ImportFailure) as e:
        linkedin.parse(make_zip(files))
    assert e.value.code == "ZIP_UNSAFE"


def test_zip_bomb_ratio():
    bomb = make_zip({"Skills.csv": "Name\n" + "a" * 5_000_000})
    with pytest.raises(ImportFailure) as e:
        linkedin.parse(bomb)
    assert e.value.code == "ZIP_UNSAFE"


def test_total_size_limit(monkeypatch):
    monkeypatch.setattr(linkedin, "MAX_TOTAL", 1000)
    with pytest.raises(ImportFailure):
        linkedin.parse(make_zip({"Skills.csv": "Name\n" + "\n".join(f"s{i}" for i in range(400))}))


def test_corrupt_zip():
    with pytest.raises(ImportFailure) as e:
        linkedin.parse(b"PK\x03\x04garbage")
    assert e.value.code == "ZIP_UNSAFE"


def test_through_api_without_llm(admin_client, fake_llm):
    r = admin_client.post(
        "/api/admin/import/linkedin",
        files={"file": ("Basic_LinkedInDataExport.zip", export())},
        headers=csrf(admin_client),
    )
    assert r.status_code == 202, r.text
    job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").json()
    assert job["status"] == "ready" and job["source_text"] is None
    assert fake_llm.streams == []  # deterministic: no AI involved
    secs = job["draft"]["sections"]
    assert set(secs) >= {"identity", "experiences", "educations", "skills", "projects", "links"}


def test_api_reports_unsafe_zip(admin_client):
    r = admin_client.post(
        "/api/admin/import/linkedin",
        files={"file": ("x.zip", make_zip({"../x": "y"}))},
        headers=csrf(admin_client),
    )
    job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and job["error_code"] == "ZIP_UNSAFE"
