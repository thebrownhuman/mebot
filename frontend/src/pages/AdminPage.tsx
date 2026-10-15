import { useEffect, useState } from "react";
import ChatScreen from "../components/ChatScreen";
import SessionsDrawer from "../components/SessionsDrawer";
import AdminDrawer from "../components/AdminDrawer";
import UnansweredPanel from "../components/admin/UnansweredPanel";
import { useChat } from "../hooks/useChat";

// Admin dashboard: activity + sessions, and a chat to try the bot as visitors see it.
// Profile data lives on its own pages (see components/admin).
export default function AdminPage() {
  const chat = useChat();
  const [open, setOpen] = useState<"sessions" | "admin" | null>("admin");

  useEffect(() => {
    void chat.connect("admin");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toolbar = (
    <div className="flex flex-wrap gap-2 mb-2.5">
      <Btn
        active={open === "sessions"}
        onClick={() => setOpen(open === "sessions" ? null : "sessions")}
      >
        sessions
      </Btn>
      <Btn active={open === "admin"} onClick={() => setOpen(open === "admin" ? null : "admin")}>
        activity
      </Btn>
      <Btn active={false} onClick={() => chat.newSession("admin")}>
        new session
      </Btn>
    </div>
  );

  const drawers = (
    <>
      <UnansweredPanel onOpen={(sid) => void chat.loadSession(sid)} />
      <SessionsDrawer open={open === "sessions"} onPick={(sid) => void chat.loadSession(sid)} />
      <AdminDrawer open={open === "admin"} />
    </>
  );

  return (
    <ChatScreen
      title="admin panel"
      conn={chat.conn}
      lines={chat.lines}
      busy={chat.busy}
      ready={chat.ready}
      orbState={chat.orbState}
      pulseRef={chat.pulseRef}
      onSend={chat.send}
      toolbar={toolbar}
      drawers={drawers}
    />
  );
}

function Btn({
  children,
  onClick,
  active,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={
        "font-mono text-xs px-2.5 py-1.5 rounded border " +
        (active
          ? "border-term-bright text-term-bright bg-term-bright/10"
          : "bg-term-panel/70 border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright")
      }
    >
      {children}
    </button>
  );
}
