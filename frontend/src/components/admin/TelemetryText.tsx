// The one place that spells out what the mebot project receives. The setup page, the
// Account page and the README all say the same thing.

// Relative on purpose: the public repo URL isn't settled yet (README "Telemetry & registration").
export const TELEMETRY_DOCS = "README.md#telemetry";

export const CONSENT_LABEL =
  "Register this install with the mebot project (sends your email, site URL and version) to get security alerts and updates.";

export function WhatIsSent({ registryUrl }: { registryUrl?: string }) {
  return (
    <div className="text-xs text-term-dim leading-relaxed space-y-2">
      <p>
        <span className="text-term-fg">Always, unless the server sets TELEMETRY=off:</span> about
        once a day an anonymous heartbeat with a random install id, its public key, the mebot
        version and the mode (<code>single</code> or <code>hosted</code>). The registry stores no
        IP address, hostname, URL, e-mail or usage data from it. mebot also asks the registry for
        the latest version and security advisories.
      </p>
      <p>
        <span className="text-term-fg">Only if you tick the box:</span> your contact e-mail, your
        site URL (PUBLIC_URL) and the version are registered, and the maintainer gets a
        notification. Untick it any time and the registration is deleted.
      </p>
      <p>
        <span className="text-term-fg">Never sent:</span> chats, your profile, API keys, contacts,
        or anything else from your install.
        {registryUrl ? ` Everything goes to ${registryUrl} and nowhere else.` : ""}
      </p>
    </div>
  );
}
