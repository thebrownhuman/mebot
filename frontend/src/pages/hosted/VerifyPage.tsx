import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CenteredCard } from "../../components/AuthForm";
import { ApiError, verifyEmail } from "../../lib/api";

export default function VerifyPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"busy" | "ok" | "error">(token ? "busy" : "error");
  const [message, setMessage] = useState("This link is incomplete.");
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true; // single-use token: never POST it twice (StrictMode)
    verifyEmail(token)
      .then(() => setState("ok"))
      .catch((e: unknown) => {
        setMessage(e instanceof ApiError ? e.message : "Could not verify. Please try again.");
        setState("error");
      });
  }, [token]);

  return (
    <CenteredCard title="// verify e-mail">
      {state === "busy" && (
        <p role="status" className="text-term-dim text-sm">
          confirming…
        </p>
      )}
      {state === "ok" && (
        <p className="text-term-fg text-sm">
          Your e-mail is confirmed.{" "}
          <Link to="/admin/login" className="text-term-bright underline">
            Log in
          </Link>{" "}
          to set up your assistant.
        </p>
      )}
      {state === "error" && (
        <p role="alert" className="text-term-err text-sm">
          {message} You can ask for a new link after logging in.
        </p>
      )}
    </CenteredCard>
  );
}
