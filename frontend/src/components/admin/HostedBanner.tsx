import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHostedAccount, resendVerification, type HostedAccount } from "../../lib/api";
import { useSetup } from "../SetupGate";

// Hosted mode: tells a new owner what still keeps their assistant offline.
export default function HostedBanner() {
  const { hosted } = useSetup();
  const [acct, setAcct] = useState<HostedAccount | null>(null);
  const [resent, setResent] = useState(false);

  useEffect(() => {
    if (!hosted) return;
    getHostedAccount()
      .then(setAcct)
      .catch(() => setAcct(null)); // the banner is a hint; pages show their own errors
  }, [hosted]);

  if (!hosted || !acct || acct.live) return null;
  return (
    <div role="status" className="mb-4 border border-term-amber/60 rounded px-3 py-2 text-sm text-term-fg">
      <span className="text-term-amber">Your assistant is offline.</span>{" "}
      {!acct.setup_done && (
        <>
          <Link to="/admin/get-started" className="text-term-bright underline">
            Finish setup
          </Link>{" "}
        </>
      )}
      {acct.setup_done && acct.email_verified && acct.billing_enabled && !acct.serving && (
        <>
          Your plan isn't active.{" "}
          <Link to="/admin/billing" className="text-term-bright underline">
            Choose a plan
          </Link>
        </>
      )}
      {!acct.email_verified && (
        <>
          Confirm your e-mail ({acct.email}).{" "}
          <button
            type="button"
            disabled={resent}
            onClick={() => resendVerification(acct.email).then(() => setResent(true), () => {})}
            className="text-term-bright underline disabled:no-underline disabled:text-term-dim"
          >
            {resent ? "link sent" : "resend link"}
          </button>
        </>
      )}
    </div>
  );
}
