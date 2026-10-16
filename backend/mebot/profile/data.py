"""Load a bot's whole structured profile (plain dicts) for rendering."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mebot.profile.sections import SECTIONS
from mebot.repos import learned_facts
from mebot.repos import profile_items as repo


@dataclass
class ProfileData:
    identity: dict = field(default_factory=dict)
    notes: str = ""
    # section slug -> items in display order (see profile.sections.SECTIONS)
    sections: dict[str, list[dict]] = field(default_factory=dict)
    # Owner-approved free-text facts, newest first (mebot.repos.learned_facts).
    learned: list[str] = field(default_factory=list)

    def items(self, slug: str) -> list[dict]:
        return self.sections.get(slug, [])


def load_profile(db: Session, bot_id: str) -> ProfileData:
    identity = repo.get_identity(db, bot_id)
    notes = repo.get_notes(db, bot_id)
    return ProfileData(
        identity=repo.serialize(None, identity) if identity else {},
        notes=notes.content if notes else "",
        sections={
            slug: [repo.serialize(sec, r) for r in repo.list_items(db, sec, bot_id)]
            for slug, sec in SECTIONS.items()
        },
        learned=[f.fact_text for f in learned_facts.active_learned(db, bot_id)],
    )
