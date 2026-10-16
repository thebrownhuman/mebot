// Mirrors backend mebot/persona.py render_greeting so the Identity page can preview the
// assistant's first bubble without a request.

export const PRONOUNS = ["he/him", "she/her", "they/them"] as const;
export type Pronouns = (typeof PRONOUNS)[number];

export const DEFAULT_GREETING =
  "Hi! I'm {first_name}'s assistant. Ask me anything about {pronoun_obj} work, experience or projects.";

const FORMS: Record<Pronouns, { subj: string; poss: string }> = {
  "he/him": { subj: "he", poss: "his" },
  "she/her": { subj: "she", poss: "her" },
  "they/them": { subj: "they", poss: "their" },
};

export function renderGreeting(
  template: string,
  fullName: string,
  pronouns: string,
  botName = "",
): string {
  const form = FORMS[pronouns as Pronouns] ?? FORMS["they/them"];
  const first = fullName.trim().split(/\s+/)[0] || botName.trim().split(/\s+/)[0] || "the owner";
  const values: Record<string, string> = {
    first_name: first,
    name: fullName.trim() || botName || first,
    pronoun_subj: form.subj,
    pronoun_obj: form.poss,
  };
  const tpl = template.trim() || DEFAULT_GREETING;
  return tpl.replace(/\{(\w+)\}/g, (m, key: string) => values[key] ?? m);
}
