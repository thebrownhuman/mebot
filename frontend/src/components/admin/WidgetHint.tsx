import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWidgetSettings } from "../../lib/api";

// Dashboard nudge: the widget is on but no site is allowed to show it.
export default function WidgetHint() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    getWidgetSettings()
      .then((w) => setShow(Boolean(w?.needs_origins)))
      .catch(() => setShow(false));
  }, []);

  if (!show) return null;
  return (
    <div className="border border-term-line2 text-term-dim rounded px-3 py-2 mb-3 text-xs">
      Want the chat on your portfolio? Add your site to the widget's allowed list first.{" "}
      <Link to="/admin/widget" className="underline text-term-bright">
        Set up the widget
      </Link>
    </div>
  );
}
