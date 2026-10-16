"""Registry of list sections: URL slug -> ORM model + input schema."""

from dataclasses import dataclass

from pydantic import BaseModel

from mebot.models import (
    AvoidTopic,
    Education,
    Experience,
    Faq,
    Interest,
    ProfileLink,
    Project,
    Skill,
)
from mebot.profile import schemas as s

MAX_ITEMS = 200
MAX_CHANNELS = 30


@dataclass(frozen=True)
class Section:
    slug: str
    model: type
    schema: type[BaseModel]
    json_fields: tuple[str, ...] = ()
    max_items: int | None = None  # None: the module-wide MAX_ITEMS

    @property
    def limit(self) -> int:
        return self.max_items or MAX_ITEMS


SECTIONS: dict[str, Section] = {
    sec.slug: sec
    for sec in (
        Section("links", ProfileLink, s.LinkIn, max_items=MAX_CHANNELS),
        Section("experiences", Experience, s.ExperienceIn, ("highlights", "tech")),
        Section("educations", Education, s.EducationIn),
        Section("skills", Skill, s.SkillIn),
        Section("projects", Project, s.ProjectIn, ("highlights", "tech")),
        Section("interests", Interest, s.InterestIn),
        Section("faqs", Faq, s.FaqIn),
        Section("avoid-topics", AvoidTopic, s.AvoidTopicIn),
    )
}


def get_section(slug: str) -> Section | None:
    return SECTIONS.get(slug)
