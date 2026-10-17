import { useEffect, useState } from "react";
import { ApiError, getPublicConfig } from "../../lib/api";
import RecruiterPage from "../RecruiterPage";

// /b/{slug}: the recruiter page of one hosted bot. An unknown, suspended or deleted bot
// gets the same neutral page (no reason is ever shown).
export default function TenantGate() {
  const [state, setState] = useState<"loading" | "ok" | "unavailable" | "error">("loading");

  useEffect(() => {
    getPublicConfig()
      .then(() => setState("ok"))
      .catch((e: unknown) => setState(e instanceof ApiError && e.status === 404 ? "unavailable" : "error"));
  }, []);

  if (state === "ok") return <RecruiterPage />;
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black px-4 text-center">
      {state === "loading" && (
        <p role="status" className="text-term-dim text-sm">
          loading…
        </p>
      )}
      {state === "unavailable" && (
        <div>
          <h1 className="text-term-bright text-lg mb-2">This assistant is unavailable</h1>
          <p className="text-term-dim text-sm">Please check the link or try again later.</p>
        </div>
      )}
      {state === "error" && (
        <p role="alert" className="text-term-err text-sm">
          Can't reach the server. Please try again in a minute.
        </p>
      )}
    </div>
  );
}
