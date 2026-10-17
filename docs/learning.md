# How mebot learns

Every professional question the bot can't answer lands in **Admin → Open questions**
(and the sidebar badge counts them). Similar wordings are grouped and counted, so
"What's his notice period?" and "notice period?" become one line, "asked 4×". No AI
call is used for grouping.

1. **You answer** in plain words, in Admin or from Telegram ("Bangalore, open to remote").
2. **One AI call** (with your own provider key, a few cents at most) turns it into a
   clean third-person fact: "Shivansh lives in Bangalore and is open to remote work."
   It may only use what you wrote. mebot then checks that every number, link and
   e-mail in the result appears in your answer; if not, or if the AI fails, the fact
   falls back to your own words, marked **needs review**.
3. **You approve.** Nothing is known to the bot until you press **Approve** (you can
   **Edit** first, or **Reject**, which puts the question back in the inbox).
   - A fact about a single profile field (location, notice period, open to, salary
     expectation, work authorisation) fills that field on the Identity page if it is
     empty. If it already has a value you choose **Replace** or **Keep both**; mebot
     never overwrites it silently.
   - Anything else becomes a **learned fact** (Memory page). The bot gets them in a
     `LEARNED FACTS` section, newest first, as authoritative as the rest of your
     profile. Only the newest 200 are used; Preview warns when you reach that, so move
     old ones into FAQ or projects.
4. **Delete** a learned fact any time and the bot stops saying it (the question reopens).

You are the only teacher: recruiter statements are never learned. Approving twice, or
in Admin and Telegram at once, does nothing the second time.

**In Telegram** (see below), after you reply to a "couldn't answer" notice, **Save to
memory** shows the cleaned fact with **Approve / Edit / Reject**. The daily digest lists
your top 3 open questions with **Answer** buttons, and `/questions` lists the top 5.
You are pinged about a question on its first ask and then at most once a day ("asked 3×").
