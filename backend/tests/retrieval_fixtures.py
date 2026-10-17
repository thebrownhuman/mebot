"""A large profile (10 jobs, 40 projects) for retrieval tests; pure data, no DB."""

from mebot.profile.data import ProfileData
from mebot.profile.sections import SECTIONS

TOPICS = [
    ("Kafka", "streaming ingestion pipeline"),
    ("Rust", "memory-safe packet parser"),
    ("Terraform", "multi-region infrastructure modules"),
    ("GraphQL", "federated gateway"),
    ("Elasticsearch", "product search relevance tuning"),
    ("Flutter", "offline-first mobile client"),
    ("Redis", "distributed rate limiter"),
    ("Kubernetes", "autoscaling job scheduler"),
    ("PostgreSQL", "partitioned analytics warehouse"),
    ("WebAssembly", "in-browser image editor"),
]


def _v(slug: str, raw: dict) -> dict:
    return SECTIONS[slug].schema.model_validate(raw).model_dump()


def large_profile() -> ProfileData:
    projects = []
    for i in range(40):
        tech, what = TOPICS[i % len(TOPICS)]
        projects.append(
            _v(
                "projects",
                {
                    "name": f"Project {tech} {i}",
                    "tagline": f"{what} number {i}",
                    "summary": f"Built a {what} using {tech}. " + "Details follow. " * 8,
                    "tech": [tech, "Docker"],
                    "highlights": [f"Handled {i + 1}00 requests per second"],
                    "start_month": "2020-01",
                },
            )
        )
    jobs = []
    for i in range(10):
        jobs.append(
            _v(
                "experiences",
                {
                    "company": f"Company{i}",
                    "title": f"Engineer level {i}",
                    "start_month": f"{2010 + i}-01",
                    "end_month": f"{2010 + i}-12" if i < 9 else None,
                    "description": f"Worked on the unique-widget-{i} platform. " + "x " * 40,
                    "highlights": [f"Shipped feature-{i}"],
                    "tech": ["Python"],
                },
            )
        )
    skills = [_v("skills", {"name": n, "category": "language"}) for n in ("Python", "Go", "Rust")]
    faqs = [_v("faqs", {"question": "Would you relocate?", "answer": "Yes, within the EU."})]
    return ProfileData(
        identity={"full_name": "Sam Large", "headline": "Engineer", "pronouns": "they/them"},
        notes="Likes mentoring. " * 200,
        sections={
            "projects": projects,
            "experiences": jobs,
            "skills": skills,
            "faqs": faqs,
        },
        learned=["Sam speaks fluent Portuguese.", "Sam won the 2019 Hackathon."],
    )
