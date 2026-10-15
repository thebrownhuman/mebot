# Spec: learning-loop

**Created**: 2026-10-16
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 7b)

---

## Problem

When the bot doesn't know something ("Where does he live?"), it says so — but it never gets better. The owner answers the recruiter once (via Telegram, #7) and the knowledge is lost unless they manually edit their profile. Repeated questions pile up unseen. The bot also speaks *as* the owner in the first person, but the owner wants it to be **their assistant** ("I'm Shivansh's assistant…"). And it must stay strictly professional: personal questions (relationships, religion, health…) are declined and never bother the owner.

## Goal

1. The bot introduces itself and speaks as the owner's assistant, in the third person.
2. Every unanswered professional question lands in an **Open questions** inbox (grouped, with counts). The owner answers from admin or Telegram; an AI turns the answer into a clean fact; the owner **approves** it; from then on the bot knows it.
3. Personal / protected topics are always politely declined, not logged as open questions, and never sent to the owner.
4. The bot only ever states facts from the profile, computed facts, or approved learned facts.

## User Stories

- As a **recruiter**, I ask "Where is he based?" → "I don't have that detail yet — I've noted it for Shivansh. You can reach him at …" Next week, I ask again and get "Shivansh is based in Bangalore and is open to remote work."
- As the **owner**, I open Admin → Open questions and see "Where do you live? — asked 4×". I type "Bangalore, open to remote", see the cleaned fact, tap Approve.
- As the **owner**, I reply in Telegram; the bot shows "Save to memory: *Shivansh lives in Bangalore and is open to remote work.*" with Approve / Edit / Reject.
- As a **recruiter**, I ask "Does he have a girlfriend?" → "That's personal, so I can't share it. Happy to help with his work and experience." The owner is never pinged.

## Requirements

### Must-have
1. **Assistant persona** (rewrite #5 `build_system_prompt` + renderer wording):
   - Identity: "You are {display_name}'s AI assistant." Third person always ("Shivansh has…", "He built…"). Pronoun from new `profile_identity.pronouns` (`he/him` | `she/her` | `they/them`, default `they/them`); when `they/them`, use the name or "they".
   - FACTS sentences rendered in third person with the name.
   - Configurable greeting `profile_identity.assistant_greeting` (default: "Hi! I'm {first_name}'s assistant. Ask me anything about {pronoun_obj} work, experience or projects."). Recruiter UI shows it as the first bot bubble (not an LLM call).
   - If asked, it says it's an AI assistant (kept from #5).
   - Update golden evals (`backend/evals/golden.yaml`) for third person.
2. **Professional filter** `mebot/guard/personal.py`:
   - Built-in categories (always on, not editable in v1): romantic relationships/dating, sexual orientation, religion/caste, politics, health/medical/disability, pregnancy/family planning, marital status, age/date of birth, ethnicity/race, finances unrelated to salary, home address beyond city.
   - Two layers: (a) input keyword/regex classifier (English + common Hinglish terms, e.g. "girlfriend", "gf", "married", "shaadi", "religion", "caste", "kaunsi jaati"); (b) prompt rule: decline these even if phrased indirectly, end with marker `[[PERSONAL]]`.
   - Stream filter (extend #5/#6) strips `[[PERSONAL]]`; event `PERSONAL_DECLINED` logged (no question text stored — only category); **no** open question, **no** Telegram ping, `messages.unanswered` stays false.
   - Owner data in these categories (e.g. owner typed marital status in notes) is still not volunteered — the prompt rule wins; document this.
   - Salary, notice period, work authorization, location (city), relocation remain allowed if the owner provided them.
3. **Open questions** (Alembic 0009) `open_questions`: `id`, `bot_id`, `question` (canonical, first-seen text), `normalized` (lowercased, punctuation/stopwords stripped), `ask_count INT`, `first_asked_at`, `last_asked_at`, `last_session_id`, `status` (`open`|`answered`|`dismissed`|`never`), `answered_fact_id NULL`, `created_at`, `updated_at`.
   - On `UNANSWERED`: find an `open` question for the bot with token-set Jaccard ≥ 0.6 on `normalized` (or exact normalized match) → increment; else insert. (No LLM call for grouping in v1.)
   - #7 unanswered Telegram ping only on **first** ask of a group and then at most once per 24h per group ("asked 3× today").
4. **Learned facts** (Alembic 0009) `learned_facts`: `id`, `bot_id`, `open_question_id NULL`, `question`, `answer_raw`, `fact_text`, `suggested_section` (`identity`|`learned`), `suggested_field NULL` (e.g. `location`, `notice_period`, `open_to`, `salary_expectation`, `work_authorization`), `suggested_value NULL`, `status` (`pending`|`approved`|`rejected`), `source` (`admin`|`telegram`), `approved_at NULL`, `created_at`, `updated_at`, `deleted_at NULL`.
5. **Cleaning step** `mebot/learning/clean.py`: one LLM call with the owner's provider; input = question + owner answer + owner name/pronouns; output strict JSON `{ fact_text, section, field, value }` validated with pydantic; rules: third person, only information present in the answer, no embellishment, ≤ 300 chars. Post-check: numbers/URLs/emails in `fact_text` must appear in `answer_raw` — else fall back to `fact_text = "{Name}: {answer_raw}"` and flag `needs_review`. LLM failure → same fallback. Personal-category answers rejected with a message.
6. **Approval:**
   - Approve with `section=identity` and the field empty → write value to `profile_identity.<field>` and mark fact approved (fact also kept for history). Field already set → show current vs new; owner chooses Replace or Keep both (keep → stored as learned fact).
   - Approve with `section=learned` → fact becomes active.
   - Edit → owner edits `fact_text` (and field/value) then approves.
   - Reject → status rejected; open question goes back to `open`.
   - Approved → linked open question → `answered`.
7. **Renderer:** new `LEARNED FACTS (confirmed by {name})` section with approved, non-deleted learned facts (newest first, cap 200, preview warns on size). Prompt rule: these are as authoritative as profile data.
8. **Telegram (#7 integration):**
   - Replace #7's "Save to FAQ" button with **Save to memory** → runs cleaning → bot replies with the cleaned fact + inline **Approve / Edit / Reject**. Edit → force_reply "Send the corrected fact".
   - Daily digest adds "Open questions (top 3 by count)" each with an **Answer** button (force_reply → same pipeline).
   - New command `/questions` → top 5 open questions with Answer buttons.
   - Recruiter delivery from #7 is unchanged (owner reply still shown in chat immediately; saving to memory is separate).
9. **Admin API:**
   - `GET /api/admin/open-questions?status=open` → items sorted by `ask_count desc, last_asked_at desc`.
   - `POST /api/admin/open-questions/{id}/answer` `{ "answer": "…" }` → runs cleaning → returns pending learned fact.
   - `POST /api/admin/open-questions/{id}/dismiss` · `POST /api/admin/open-questions/{id}/never` (also adds an avoid-topic with default reply).
   - `GET /api/admin/learned-facts?status=…` · `POST /api/admin/learned-facts` (owner adds a fact directly, goes through cleaning) · `POST …/{id}/approve` `{ fact_text?, field?, value?, mode?: "replace"|"keep_both" }` · `POST …/{id}/reject` · `PUT …/{id}` · `DELETE …/{id}` (soft).
10. **Admin UI:**
    - **Open questions** page (sidebar badge with open count): list with count + last asked; inline answer box → shows cleaned fact card with Approve / Edit / Reject; Dismiss; "Never answer this".
    - **Memory** page: approved learned facts (edit/delete), pending facts awaiting approval, rejected (collapsed).
    - Identity page: pronouns select, assistant greeting field with preview.
    - Dashboard: replace #5 "Unanswered" list with "Open questions" summary + link.
11. **Docs:** README "How mebot learns" + "What mebot will never discuss".

### Nice-to-have
- LLM-assisted grouping of similar questions.
- "Suggested questions to answer" generated from gaps in the profile.

### Out of scope
- Embedding search (#14).
- Owner-editable personal categories.
- Learning from recruiter statements (only the owner teaches the bot).

## Data Model

Alembic 0009: `open_questions`, `learned_facts`, `profile_identity.pronouns`, `profile_identity.assistant_greeting`. snake_case, UUID ids, UTC timestamps, soft delete on `learned_facts`.

## API Changes

```
GET  /api/admin/open-questions?status=open → { "items": [{ "id": "…", "question": "Where do you live?", "ask_count": 4, "last_asked_at": "2026-10-16T09:00:00Z", "status": "open" }] }
POST /api/admin/open-questions/{id}/answer { "answer": "Bangalore, open to remote" }
  → 201 { "id": "…", "status": "pending", "fact_text": "Shivansh lives in Bangalore and is open to remote work.",
          "suggested_section": "identity", "suggested_field": "location", "suggested_value": "Bangalore (open to remote)",
          "current_value": null, "needs_review": false }
POST /api/admin/learned-facts/{id}/approve { "mode": "replace" } → 200 { ...fact, "status": "approved" }
POST /api/admin/learned-facts/{id}/reject → 200
```

## UI Changes

New Open questions + Memory pages; Identity pronouns/greeting; recruiter greeting bubble; Telegram buttons.

## Edge Cases

1. Same question worded differently ("where r u based", "Where do you live?") → grouped when Jaccard ≥ 0.6; otherwise separate (owner can dismiss duplicates).
2. Owner answer contains personal info ("Bangalore, with my girlfriend") → cleaning drops personal part; if only personal → rejected with message.
3. Cleaning LLM invents detail ("…since 2019") not in answer → post-check fallback + needs_review.
4. LLM key not working → fallback fact, still approvable.
5. Identity field already set → Replace/Keep both choice; never silently overwritten.
6. Owner approves from Telegram and admin at the same time → idempotent; second approve no-op.
7. Personal question phrased indirectly ("is he single?") → declined via prompt rule + marker; no open question.
8. A professional question accidentally caught by keyword list (e.g. "Religare company") → word-boundary regex; layer (b) decides; false positives covered by tests.
9. Recruiter asks about something the owner later deleted → fact soft-deleted → bot no longer states it.
10. 200+ learned facts → cap with preview warning; suggests moving to profile sections.
11. Pronouns `they/them` → grammar uses name/"they"; evals cover all three.

## Testing Criteria

- Persona: system prompt third person; greeting rendered; FACTS sentences third person for each pronoun; evals updated (run against FakeLLM).
- Personal filter: keyword classifier positives/negatives (incl. Hinglish, word boundaries); `[[PERSONAL]]` stripped (split across chunks); `PERSONAL_DECLINED` logged without question text; no open question; no Telegram notification.
- Open questions: grouping thresholds; counts; Telegram ping dedup (first + 24h).
- Cleaning: valid JSON path; invalid JSON / LLM error fallback; number/URL/email post-check; personal answer rejected.
- Approval: identity empty → written; identity set → replace/keep_both; learned section; edit; reject reopens question; idempotent approve.
- Renderer: LEARNED FACTS section present/omitted; deleted facts excluded.
- Telegram: Save to memory → Approve/Edit/Reject callbacks; digest open questions; `/questions`.
- Admin API auth/CSRF/bot scope; frontend pages with mocked API.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–7 (`feature/telegram`).
- No new deps.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Soft delete (learned_facts)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 11 edge cases · [x] Happy + edge tests · [x] Dependencies listed
