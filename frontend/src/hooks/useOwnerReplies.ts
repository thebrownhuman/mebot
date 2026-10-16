import { useCallback, useEffect, useRef } from "react";
import { ApiError, getSessionUpdates, type SessionUpdates } from "../lib/api";

// Polls GET /api/session/{sid}/updates for the owner's replies (sent from Telegram).
// Every POLL_MS while the tab is visible; stops when it's hidden or after IDLE_MS
// without activity, and resumes on the next key press / tap / tab focus.

export const POLL_MS = 5000;
export const IDLE_MS = 30 * 60 * 1000;
const ACTIVITY = ["keydown", "pointerdown", "touchstart", "focus"] as const;

function visible() {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function useOwnerReplies(
  sid: string | null,
  onUpdates: (u: SessionUpdates) => void,
  enabled = true,
) {
  const after = useRef<string | null>(null);
  const lastActivity = useRef(Date.now());
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlight = useRef(false);
  const pausedUntil = useRef(0); // server said Retry-After
  const cb = useRef(onUpdates);
  cb.current = onUpdates;

  const poll = useCallback(async () => {
    if (!sid || inFlight.current || Date.now() < pausedUntil.current) return;
    inFlight.current = true;
    try {
      const u = await getSessionUpdates(sid, after.current);
      const last = u.messages[u.messages.length - 1];
      if (last) after.current = last.created_at;
      cb.current(u);
    } catch (e) {
      if (e instanceof ApiError && e.retryAfter) {
        pausedUntil.current = Date.now() + e.retryAfter * 1000;
      }
      // otherwise transient: try again next tick
    } finally {
      inFlight.current = false;
    }
  }, [sid]);

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  const start = useCallback(() => {
    if (timer.current || !sid || !enabled || !visible()) return;
    timer.current = setInterval(() => {
      if (!visible() || Date.now() - lastActivity.current > IDLE_MS) {
        stop();
        return;
      }
      void poll();
    }, POLL_MS);
  }, [sid, enabled, poll, stop]);

  // New session: forget the cursor, fetch right away, start the timer.
  useEffect(() => {
    after.current = null;
    lastActivity.current = Date.now();
    if (!sid || !enabled) return;
    void poll();
    start();
    return stop;
  }, [sid, enabled, poll, start, stop]);

  useEffect(() => {
    if (!sid || !enabled) return;
    const onActivity = () => {
      const wasStopped = timer.current === null;
      lastActivity.current = Date.now();
      if (wasStopped && visible()) {
        void poll();
        start();
      }
    };
    const onVisibility = () => {
      if (visible()) onActivity();
      else stop();
    };
    for (const ev of ACTIVITY) window.addEventListener(ev, onActivity);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      for (const ev of ACTIVITY) window.removeEventListener(ev, onActivity);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [sid, enabled, poll, start, stop]);

  // Check now (e.g. right after the bot answered), and count it as activity.
  const pollNow = useCallback(() => {
    lastActivity.current = Date.now();
    void poll();
    start();
  }, [poll, start]);

  return { pollNow };
}
