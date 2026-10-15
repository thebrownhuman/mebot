import type { ProfileItem, ProfileSection } from "../../lib/api";
import type { FieldDef } from "./fields";

// One entry per collection page. `route` is the URL slug under /admin/profile/,
// `api` the backend section. Field names match the backend schemas.

export interface SectionConfig {
  route: string;
  api: ProfileSection;
  title: string;
  noun: string; // "project" -> "Add project", "Edit project"
  intro: string;
  empty: string;
  fields: FieldDef[];
  cardTitle: (i: ProfileItem) => string;
  cardMeta?: (i: ProfileItem) => string;
}

const SHORT = 200;
const LONG = 5000;

const str = (v: unknown) => (typeof v === "string" ? v : "");
const period = (i: ProfileItem) => {
  const s = str(i.start_month);
  const e = str(i.end_month);
  if (!s && !e) return "";
  return `${s || "?"} – ${e || "present"}`;
};
const joinMeta = (...parts: unknown[]) =>
  parts.filter((p) => typeof p === "string" && p).join(" · ");

const month = (name: string, label: string, required = false, currentLabel?: string): FieldDef => ({
  name,
  label,
  kind: "month",
  required,
  currentLabel,
});

export const SECTIONS: SectionConfig[] = [
  {
    route: "experience",
    api: "experiences",
    title: "Experience",
    noun: "experience",
    intro: "Jobs with start and end months, so the bot can answer “how long at X?” exactly.",
    empty: "Add your first job — the bot will be able to walk recruiters through your career.",
    fields: [
      { name: "company", label: "Company", kind: "text", required: true, maxLength: SHORT },
      { name: "title", label: "Title", kind: "text", required: true, maxLength: SHORT },
      {
        name: "employment_type",
        label: "Employment type",
        kind: "select",
        options: [
          ["full-time", "Full-time"],
          ["part-time", "Part-time"],
          ["contract", "Contract"],
          ["internship", "Internship"],
          ["freelance", "Freelance"],
        ],
      },
      { name: "location", label: "Location", kind: "text", maxLength: SHORT },
      month("start_month", "Start month", true),
      month("end_month", "End month", false, "I currently work here"),
      { name: "description", label: "Description", kind: "textarea", maxLength: LONG },
      { name: "highlights", label: "Highlights", kind: "tags", hint: "Achievements, one per tag." },
      { name: "tech", label: "Tech", kind: "tags" },
    ],
    cardTitle: (i) => `${str(i.title)} · ${str(i.company)}`,
    cardMeta: (i) => joinMeta(period(i), i.employment_type, i.location),
  },
  {
    route: "education",
    api: "educations",
    title: "Education",
    noun: "education",
    intro: "Degrees, courses and certifications.",
    empty: "Add your education — degree, institution and dates.",
    fields: [
      { name: "institution", label: "Institution", kind: "text", required: true, maxLength: SHORT },
      { name: "degree", label: "Degree", kind: "text", required: true, maxLength: SHORT },
      { name: "field", label: "Field of study", kind: "text", maxLength: SHORT },
      month("start_month", "Start month", true),
      month("end_month", "End month", false, "I'm still studying here"),
      { name: "grade", label: "Grade", kind: "text", maxLength: SHORT },
      { name: "description", label: "Description", kind: "textarea", maxLength: LONG },
    ],
    cardTitle: (i) => `${str(i.degree)} · ${str(i.institution)}`,
    cardMeta: (i) => joinMeta(period(i), i.field),
  },
  {
    route: "skills",
    api: "skills",
    title: "Skills",
    noun: "skill",
    intro: "Languages, frameworks, tools and soft skills, with your level.",
    empty: "Add your first skill — e.g. Python, expert.",
    fields: [
      { name: "name", label: "Name", kind: "text", required: true, maxLength: SHORT },
      {
        name: "category",
        label: "Category",
        kind: "select",
        options: [
          ["language", "Language"],
          ["framework", "Framework"],
          ["tool", "Tool"],
          ["cloud", "Cloud"],
          ["soft", "Soft skill"],
          ["other", "Other"],
        ],
      },
      {
        name: "level",
        label: "Level",
        kind: "select",
        options: [
          ["beginner", "Beginner"],
          ["intermediate", "Intermediate"],
          ["advanced", "Advanced"],
          ["expert", "Expert"],
        ],
      },
      {
        name: "years_override",
        label: "Years of experience",
        kind: "number",
        hint: "Optional. Leave empty to let mebot work it out later.",
      },
      { name: "notes", label: "Notes", kind: "textarea", maxLength: LONG },
    ],
    cardTitle: (i) => str(i.name),
    cardMeta: (i) => joinMeta(i.category, i.level),
  },
  {
    route: "projects",
    api: "projects",
    title: "Projects",
    noun: "project",
    intro: "What you built and how: the bot can explain each part of the stack.",
    empty: "Add your first project — the bot will be able to explain it to recruiters.",
    fields: [
      { name: "name", label: "Name", kind: "text", required: true, maxLength: SHORT },
      { name: "tagline", label: "Tagline", kind: "text", maxLength: SHORT },
      { name: "summary", label: "Summary", kind: "textarea", required: true, maxLength: LONG },
      { name: "problem", label: "Problem it solves", kind: "textarea", maxLength: LONG },
      { name: "my_role", label: "My role", kind: "textarea", maxLength: LONG },
      { name: "frontend", label: "Frontend", kind: "textarea", maxLength: LONG },
      { name: "backend", label: "Backend", kind: "textarea", maxLength: LONG },
      { name: "infra", label: "Infrastructure", kind: "textarea", maxLength: LONG },
      { name: "data_ai", label: "Data / AI", kind: "textarea", maxLength: LONG },
      { name: "highlights", label: "Highlights", kind: "tags" },
      { name: "tech", label: "Tech", kind: "tags" },
      { name: "repo_url", label: "Repository URL", kind: "url", placeholder: "https://" },
      { name: "live_url", label: "Live URL", kind: "url", placeholder: "https://" },
      month("start_month", "Start month"),
      month("end_month", "End month"),
      {
        name: "status",
        label: "Status",
        kind: "select",
        options: [
          ["active", "Active"],
          ["completed", "Completed"],
          ["archived", "Archived"],
        ],
      },
    ],
    cardTitle: (i) => str(i.name),
    cardMeta: (i) =>
      joinMeta(i.tagline, Array.isArray(i.tech) ? (i.tech as string[]).join(", ") : ""),
  },
  {
    route: "interests",
    api: "interests",
    title: "Interests & Hobbies",
    noun: "interest",
    intro: "What you do outside work, so the bot can talk about you as a person.",
    empty: "Add a hobby or interest — the bot will be able to talk about you beyond your CV.",
    fields: [
      {
        name: "kind",
        label: "Kind",
        kind: "select",
        required: true,
        options: [
          ["hobby", "Hobby"],
          ["interest", "Interest"],
        ],
      },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: SHORT },
      { name: "description", label: "Description", kind: "textarea", maxLength: LONG },
    ],
    cardTitle: (i) => str(i.name),
    cardMeta: (i) => (i.kind === "hobby" ? "Hobby" : "Interest"),
  },
  {
    route: "faq",
    api: "faqs",
    title: "FAQ",
    noun: "question",
    intro: "Exact answers to questions recruiters often ask.",
    empty: "Add a question you get often — e.g. “Are you open to relocation?”",
    fields: [
      { name: "question", label: "Question", kind: "text", required: true, maxLength: 400 },
      { name: "answer", label: "Answer", kind: "textarea", required: true, maxLength: LONG },
    ],
    cardTitle: (i) => str(i.question),
    cardMeta: (i) => str(i.answer).slice(0, 120),
  },
  {
    route: "avoid-topics",
    api: "avoid-topics",
    title: "Avoid topics",
    noun: "topic",
    intro: "Topics the bot must never discuss, with an optional polite reply.",
    empty: "Add a topic the bot should decline — e.g. current salary.",
    fields: [
      { name: "topic", label: "Topic", kind: "text", required: true, maxLength: SHORT },
      {
        name: "reply",
        label: "Polite reply",
        kind: "textarea",
        maxLength: LONG,
        hint: "Optional. What the bot says instead.",
      },
    ],
    cardTitle: (i) => str(i.topic),
    cardMeta: (i) => str(i.reply),
  },
];

export const LINKS: SectionConfig = {
  route: "links",
  api: "links",
  title: "Links",
  noun: "link",
  intro: "GitHub, LinkedIn, portfolio, blog…",
  empty: "Add a link — GitHub, LinkedIn or your site.",
  fields: [
    { name: "label", label: "Label", kind: "text", required: true, maxLength: SHORT },
    { name: "url", label: "URL", kind: "url", required: true, placeholder: "https://" },
  ],
  cardTitle: (i) => str(i.label),
  cardMeta: (i) => str(i.url),
};

export function sectionByRoute(route: string | undefined): SectionConfig | undefined {
  return SECTIONS.find((s) => s.route === route);
}
