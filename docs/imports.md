# Imports

## Import your resume or LinkedIn

Admin → Import fills your profile from files you already have. You review every item
before anything is saved.

**Resume (PDF or .docx, up to 10 MB).** mebot reads the text and asks *your* AI provider
to sort it into jobs, education, skills, projects, interests and links, with strict
instructions to copy only what's written. Then it checks the result against the file:
company, title, school, degree, project and skill names must appear in the resume
(fuzzy, ignoring case and punctuation), and so must every year. Anything that doesn't is
marked **Check this** with the reason and starts as *Skip*. Phone numbers and personal
details (date of birth, marital status, religion and the like; see *What mebot will
never discuss*) are removed. Scanned PDFs have no text to read: use the .docx or the
LinkedIn import. Password-protected PDFs, old `.doc` and macro-enabled files are
refused. You need an AI provider set up first.

**LinkedIn export (ZIP, up to 50 MB).** No AI, so the result is exactly what LinkedIn
has. To get it: LinkedIn → Me → Settings & Privacy → Data privacy → *Get a copy of your
data* → tick Profile, Positions, Education, Skills, Projects (plus Certifications,
Languages, Honors if you want) → request it, wait for the email, upload the ZIP as is.
mebot opens **only** those CSV files (and Email Addresses). Messages, connections,
invitations, phone numbers and everything else in the archive are never read.
Certifications land in Education (shown separately), languages become skills,
honors are proposed as a note, and with several e-mail addresses only the primary one
starts ticked. Year-only dates become January of that year and are flagged.

**Review.** Each item is compared with what's already in your profile: **New** (starts as
*Add*), **Already in profile** (*Skip*), or **Changed** with a field-by-field diff
(*Update*). Jobs match on company + title + start month (±1 month), education on school +
degree, skills by name (aliases like JS/JavaScript count), projects by name. Edit any
item inline, use *Accept all new*, or *Show in source* to see where a resume item came
from. *Apply* saves everything in one go; if one item fails validation (an end date
before the start, say), nothing is saved and that item is highlighted. Re-importing an
updated file only proposes what's new or changed.

**Privacy.** The file is processed in memory and never stored or logged (the server keeps
its name, size and a SHA-256 hash, so uploading the same file twice returns the same
review). The extracted draft is kept for 7 days for you to review, then deleted (or as
soon as you apply or discard it). Limits: 10 imports per hour and one at a time.

## Import projects from GitHub

Admin → Import → **GitHub** turns public repos into project entries, through the same
review screen as resume / LinkedIn imports. Paste up to 10 repo URLs (one per line), or
enter your username and tick repos in the picker (sorted by stars, forks hidden unless
you ask).

**What's read.** Only `api.github.com`: the repo's metadata, language stats, README
(first 30,000 characters), the file list of the root plus one level into `frontend/`,
`backend/`, `client/`, `server/`, `web/`, `api/`, `apps/*`, `packages/*`, and the
contents of dependency manifests only (`package.json`, `requirements*.txt`,
`pyproject.toml`, `Pipfile`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`,
`composer.json`, `Gemfile`, `pubspec.yaml`, `Dockerfile`, `docker-compose*.yml`,
`prisma/schema.prisma`; at most 15 files of 200 KB each). Config files like
`vercel.json`, `*.tf` or `.github/workflows/*` count by name alone. Source code is never
read, and links in READMEs are never followed. Private repos can't be imported.

**How the entry is built.** Tech is detected from the manifests, not guessed: each tech
has *Evidence* (the file and key that showed it), and languages over 5% of the code are
included. Name, tagline, links, start month (repo created), end month (only for
archived repos) and status (archived / active if pushed in the last 6 months /
completed) come straight from GitHub. If you have an AI provider set up, it writes the
summary and the frontend / backend / infra / data-AI paragraphs from the README only.
The README is treated as data, not instructions. Any number or tech the text mentions
that isn't in the README or the manifests marks the entry **Check this**. Without an AI
provider the summary is the repo description, also flagged. Detected tech you don't
already list is offered as skills, unticked. Re-importing a repo matches the existing
project by its repo URL and shows only what changed.

**Rate limits and the token.** Without a token GitHub allows 60 requests an hour, enough
for about 5 repos. If you hit it, the import says when to try again. For more, create a
[fine-grained token](https://github.com/settings/personal-access-tokens/new) with **no
permissions** (public repositories, read-only is the default) and paste it under *GitHub
token* on the card, or set `GITHUB_TOKEN` on the server. A saved token is encrypted with
your `SECRET_KEY`, shown as its last 4 characters, never logged, and only sent to
`api.github.com`.
