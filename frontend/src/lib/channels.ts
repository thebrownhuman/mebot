// Contact channels (backend mebot/channels.py): what kinds exist and how to show them.

export type ChannelKind =
  | "portfolio"
  | "website"
  | "email"
  | "linkedin"
  | "github"
  | "instagram"
  | "whatsapp"
  | "telegram"
  | "x"
  | "phone"
  | "other";

export interface KindMeta {
  kind: ChannelKind;
  label: string;
  icon: string;
  placeholder: string;
  hint?: string;
}

export const CHANNEL_KINDS: KindMeta[] = [
  { kind: "portfolio", label: "Portfolio", icon: "🌐", placeholder: "https://your-site.dev" },
  { kind: "website", label: "Website", icon: "🔗", placeholder: "https://" },
  { kind: "email", label: "Email", icon: "✉️", placeholder: "you@example.com" },
  { kind: "linkedin", label: "LinkedIn", icon: "💼", placeholder: "https://linkedin.com/in/you" },
  { kind: "github", label: "GitHub", icon: "🐙", placeholder: "username or profile URL" },
  { kind: "instagram", label: "Instagram", icon: "📸", placeholder: "@handle or profile URL" },
  {
    kind: "whatsapp",
    label: "WhatsApp",
    icon: "💬",
    placeholder: "@username",
    hint: "Use your WhatsApp username, not your number",
  },
  { kind: "telegram", label: "Telegram", icon: "✈️", placeholder: "@handle or t.me link" },
  { kind: "x", label: "X", icon: "𝕏", placeholder: "@handle or profile URL" },
  {
    kind: "phone",
    label: "Phone",
    icon: "📞",
    placeholder: "+91 98765 43210",
    hint: "Not shared by default. Recruiters only see it if you turn Share on.",
  },
  { kind: "other", label: "Other link", icon: "🔗", placeholder: "https://" },
];

export const PHONE_SHARE_WARNING =
  "Sharing your phone number lets any visitor to this page see and call it. Share it only if you are sure.";
export const PHONE_SHARE_CONFIRM =
  "Share your phone number with every recruiter who opens the Contact panel or asks the bot?";

export function kindMeta(kind: unknown): KindMeta {
  return CHANNEL_KINDS.find((k) => k.kind === kind) ?? CHANNEL_KINDS[CHANNEL_KINDS.length - 1];
}

// What GET /api/public/contact-channels returns for each shared channel.
export interface PublicChannel {
  kind: ChannelKind;
  label: string;
  display: string;
  href: string | null;
}
