import type { Overview } from "../lib/api";

const kpi = (value: number | null, previous: number | null = null) => ({ value, previous });

// A brand-new bot's dashboard payload: zeros, no sources, everything healthy.
export function emptyOverview(): Overview {
  return {
    range: { key: "7d", from: "2026-10-11", to: "2026-10-17", timezone: "UTC" },
    kpis: {
      chats: kpi(0, 0),
      visitor_messages: kpi(0, 0),
      avg_messages_per_chat: kpi(null, null),
      unanswered_rate: kpi(null, null),
      open_questions: kpi(0),
      contacts: kpi(0, 0),
      owner_replies: kpi(0, 0),
      tokens: kpi(0, 0),
    },
    series: [{ date: "2026-10-17", chats: 0, visitor_messages: 0, unanswered: 0 }],
    top_questions: [],
    sources: [],
    status: {
      llm: { configured: true, ok: true, last_tested_at: null },
      telegram: { linked: true, dead: 0 },
      widget: { enabled: true, origins: 1, any_origin: false },
      paused: false,
      today: { messages: 0, cap: 500, tokens: 0, token_cap: null },
    },
  };
}

// The "mebot project" payload: not registered, nothing to update.
export function quietTelemetry() {
  return {
    telemetry: "on",
    registry_url: "https://registry.shivanshmishra.in",
    consent: false,
    status: "not_registered",
    registered_at: null,
    last_register_error: null,
    install_id_prefix: "9f2c41aa",
    update_contact_email: null,
    effective_email: "o@example.com",
    public_url: null,
    last_heartbeat: null,
    payload_preview: null,
    last_check_at: null,
    update: {
      current: "0.9.0",
      latest: null,
      available: false,
      dismissed: false,
      unsupported: false,
      advisory: null,
    },
  };
}
