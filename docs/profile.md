# Your profile and how the bot answers

## Adding your data

Everything the bot knows comes from the admin portal (`/admin`, sidebar on the
left; a menu button on phones). One page per section:

| Page | What goes there |
|---|---|
| Identity | Name, **pronouns**, headline, location, what you're open to, summary, notice period, salary expectation, work authorisation, photo URL, the **assistant greeting**, plus your **contact channels** (see *How recruiters contact you*) |
| Experience | Jobs with start/end months (tick "I currently work here" for the current one), description, highlights, tech |
| Education | Degrees and courses with dates |
| Skills | Name, category, level, optional years |
| Projects | Summary, problem, your role, frontend / backend / infrastructure / data & AI, highlights, tech, repo and live URLs |
| Interests & Hobbies | What you do outside work, so the bot can talk about you as a person |
| FAQ | Exact answers to questions you get often ("Open to relocation?") |
| Avoid topics | Things the bot must never discuss, with an optional polite reply |
| Notes | Anything else. Text from the old single profile box was moved here on upgrade |
| Open questions | Questions the bot couldn't answer, most asked first. Answer once and the bot learns it (see below). The sidebar shows how many are open |
| Memory | Facts the bot learned from you: waiting for your approval, approved, rejected. You can also add a fact directly |
| Preview | The exact text the bot receives, with a size estimate (it warns above ~6k tokens) |

Lists can be reordered with the arrow buttons; the order is the order the bot sees.
Deleting an item hides it (soft delete). Two tabs editing the same item: the last
save wins.

## How answers stay grounded

- **Numbers come from the server, not the model.** mebot computes a FACTS block from
  your dates (as of today, UTC) and puts it first in the prompt: total experience
  (overlapping jobs merged, current jobs counted up to this month), current role,
  time per company, years per skill (from the jobs and dated projects whose tech
  lists it, with common aliases like JS/JavaScript and k8s/Kubernetes, or your own
  "years" override), latest education and counts. The model is told to quote these
  and never do date math. See them on Admin → Preview.
- **Internships and freelance.** Identity has two toggles: count internships (off
  by default) and count freelance/contract work (on by default) toward the total.
- **"I don't know" is tracked.** When the profile can't answer, the bot says so
  (offering the contact channels you share, if any) and ends with a hidden
  `[[UNANSWERED]]` marker. The server strips it from the stream, flags the
  message and files the question under **Open questions**, where you can answer
  it once and the bot learns it (see *How mebot learns*).
- **The bot is your assistant, not you.** It always talks about you in the third
  person ("Shivansh has 4 years of Python…"), uses the pronouns you chose on the
  Identity page (default they/them: it then says your name or "they"), and says it
  is an AI assistant if asked. Recruiters see your **assistant greeting** as the
  first message; it is rendered by the server, not generated, so it costs nothing.
  Placeholders: `{first_name}`, `{name}`, `{pronoun_subj}`, `{pronoun_obj}`.
- **Limits.** This is prompt-level grounding: a model can still ignore its rules.
  Run the golden evals against your provider and model to check:

      cd backend
      python -m mebot.evals --bot default

  It uses `evals/sample_profile.yaml` and `evals/golden.yaml` (33 questions:
  years, roles, projects, hobbies, unknowns, off-topic, avoid-topics, a prompt
  injection, third-person persona, personal questions that must be declined, meeting and phone-number requests) and makes real API calls with your key, so it costs a few cents.

## What mebot will never discuss

mebot only talks about your work. It always declines, in one polite sentence, questions
about romantic relationships or dating, marital status, sexual orientation, religion or
caste, politics, health or disability, pregnancy or family planning, age or date of
birth, ethnicity or race, finances unrelated to salary, and a home address beyond your
city. This list is built in and can't be edited in this version.

- **Two layers.** A keyword check (English and common Hinglish, whole words only, so
  "Religare" is not "religion") flags the message; the prompt rule makes the model
  decline even indirect phrasings ("is he single?") and end with a hidden `[[PERSONAL]]`
  marker that the server strips.
- **Not logged as unanswered, never sent to you.** A declined question creates no open
  question and no Telegram message (the per-question alert and the digest skip it too).
  The log records `PERSONAL_DECLINED` with the category only, not the question text. The
  chat history itself still stores what the visitor typed, like any message.
- **Your own data doesn't override this.** If you typed something in these categories
  into Notes or an answer, the bot still won't volunteer it, and the cleaning step
  refuses to save personal answers.
- **Still allowed** when you provided them: salary expectation, notice period, work
  authorisation, your city and relocation.
- A false positive on a keyword only adds a hint for the model; it can't hide a
  professional answer. The one side effect: if the keyword matches and the model also
  says it doesn't know, the question is treated as declined instead of opening a question.

## How recruiters contact you

On **Admin → Profile → Identity** the **Contact channels** list replaces the old Links
and public email/phone fields. Each channel has a type (portfolio, website, email,
LinkedIn, GitHub, Instagram, WhatsApp, Telegram, X, phone, other), a value, a label and
a **Share with recruiters** switch. You can keep up to 30.

- **Only shared channels are ever used.** They appear in the **Contact** panel in the
  recruiter chat header (links open in a new tab), and the bot lists them when someone
  asks to meet, call, interview or hire you ("Can we set up a call?"). It also points to
  the **Leave your contact** form. It never invents times or claims it can book a
  meeting: there is no calendar feature. With nothing shared, it offers only the form.
- **A phone number is never shared by default.** Adding one keeps the switch off.
  Turning it on asks for explicit confirmation (the API needs `confirm_share_phone: true`).
- **WhatsApp takes a username, not a number.** `@yourname` or `wa.me/yourname`; a value
  with 7 or more digits is rejected and you are told to add it as a Phone channel
  instead. Handles for Instagram, X, Telegram and GitHub are turned into profile links;
  website-style types accept only `http(s)` URLs.
- **Switched-off channels are kept for you and never revealed.** They are not sent to
  the AI at all (see Admin → Preview), and an output guard also replaces any
  non-shared value in a reply (and its variants: a phone number with or without `+`
  or spaces, a handle with or without `@`) with `[hidden]`, even if the model quotes
  it in pieces. Any phone-shaped string of 10+ digits is hidden unless it is your shared
  phone. The Logs show `CHANNEL_REDACTED` with a count, never the value. Turning a
  switch off takes effect on the very next message.
- **Don't put your number in Notes or FAQ.** The guard hides it anyway, but Preview
  warns "A phone number appears in your notes", so you can move it to a Phone channel.
- **Limits of the guard:** it can't know a made-up address is wrong. If the AI invents
  an email, it is not one of yours; the prompt forbids it and the golden evals check
  the common cases.
- **Upgrading:** existing links become channels (kind guessed from the domain, shared);
  the old public email becomes a shared Email channel and the old public phone becomes
  a Phone channel that is **not** shared. The old Identity columns stay in the database
  but are no longer used.

Public API: `GET /api/public/contact-channels` returns only the shared channels
(`kind`, `label`, `display`, `href`) and is rate limited.
