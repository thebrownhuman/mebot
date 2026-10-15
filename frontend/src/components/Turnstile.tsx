import { useEffect, useRef } from "react";

// Cloudflare Turnstile. The script is only loaded when the owner configured it.
const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileApi {
  render: (
    el: HTMLElement,
    opts: {
      sitekey: string;
      callback: (token: string) => void;
      "error-callback"?: () => void;
      theme?: string;
    },
  ) => string;
  remove: (id: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SCRIPT_SRC;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => {
        loading = null;
        reject(new Error("Could not load the verification check."));
      };
      document.head.appendChild(s);
    });
  }
  return loading;
}

export default function Turnstile({
  siteKey,
  onToken,
  onError,
}: {
  siteKey: string;
  onToken: (token: string) => void;
  onError: (message: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef({ onToken, onError });
  cb.current = { onToken, onError };

  useEffect(() => {
    let id: string | null = null;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !ref.current || !window.turnstile) return;
        id = window.turnstile.render(ref.current, {
          sitekey: siteKey,
          theme: "dark",
          callback: (t) => cb.current.onToken(t),
          "error-callback": () => cb.current.onError("Verification failed. Please refresh the page."),
        });
      })
      .catch((e: Error) => cb.current.onError(e.message));
    return () => {
      cancelled = true;
      if (id && window.turnstile) window.turnstile.remove(id);
    };
  }, [siteKey]);

  return <div ref={ref} aria-label="verification check" className="my-2" />;
}
