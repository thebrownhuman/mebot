import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getTelegram } from "../../lib/api";

// Dashboard nudge: Telegram isn't linked, so the owner hears about nothing.
export default function TelegramHint() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    getTelegram()
      .then((t) => setShow(!t?.linked))
      .catch(() => setShow(false));
  }, []);

  if (!show) return null;
  return (
    <div className="border border-term-line2 text-term-dim rounded px-3 py-2 mb-3 text-xs">
      Telegram isn't linked — link it to hear about new chats and reply to questions the bot
      couldn't answer.{" "}
      <Link to="/admin/notifications" className="underline text-term-bright">
        Set up notifications
      </Link>
    </div>
  );
}
