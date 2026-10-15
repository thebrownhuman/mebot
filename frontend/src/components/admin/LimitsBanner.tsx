import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getLimits,
  getUsage,
  type LimitsView,
  type UsageDay,
} from "../../lib/api";

const WARN_AT = 0.8;

// Dashboard warnings: bot paused, or most of today's message cap used.
export default function LimitsBanner() {
  const [limits, setLimits] = useState<LimitsView | null>(null);
  const [today, setToday] = useState<UsageDay | null>(null);

  useEffect(() => {
    getLimits()
      .then(setLimits)
      .catch(() => setLimits(null));
    getUsage(1)
      .then((u) => setToday(u?.days?.[0] ?? null))
      .catch(() => setToday(null));
  }, []);

  if (!limits) return null;
  const used = today?.messages ?? 0;
  const ratio = limits.daily_message_cap ? used / limits.daily_message_cap : 0;
  if (!limits.paused && ratio < WARN_AT) return null;

  return (
    <div
      role="status"
      className={
        "border rounded px-3 py-2 mb-3 text-xs " +
        (limits.paused || ratio >= 1
          ? "border-term-err text-term-err"
          : "border-term-amber text-term-amber")
      }
    >
      {limits.paused
        ? "The bot is paused: visitors can't chat until you resume it."
        : ratio >= 1
          ? `Today's message cap is reached (${used}/${limits.daily_message_cap}); chats resume at 00:00 UTC.`
          : `You've used ${Math.floor(ratio * 100)}% of today's message cap (${used}/${limits.daily_message_cap}).`}{" "}
      <Link to="/admin/limits" className="underline text-term-bright">
        Open limits
      </Link>
    </div>
  );
}
