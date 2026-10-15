import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ChatScreen from "../components/ChatScreen";
import ProfileDrawer from "../components/ProfileDrawer";
import SessionsDrawer from "../components/SessionsDrawer";
import AdminDrawer from "../components/AdminDrawer";
import { useChat } from "../hooks/useChat";
import { logout, type Me } from "../lib/api";

interface Props {
  me: Me;
}

export default function AdminPage({ me }: Props) {
  const chat = useChat();
  const navigate = useNavigate();
  const [open, setOpen] = useState<"profile" | "sessions" | "admin" | null>("admin");
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    void chat.connect("admin");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doLogout() {
    setLoggingOut(true);
    try {
      await logout();
    } catch {
      // Cookie is cleared server-side on success; on failure still leave the panel.
    }
    navigate("/admin/login", { replace: true });
  }

  const toolbar = (
    <div className="flex gap-2 mb-2.5">
      <Btn active={open === "profile"} onClick={() => setOpen(open === "profile" ? null : "profile")}>
        profile
      </Btn>
      <Btn active={open === "sessions"} onClick={() => setOpen(open === "sessions" ? null : "sessions")}>
        sessions
      </Btn>
      <Btn active={open === "admin"} onClick={() => setOpen(open === "admin" ? null : "admin")}>
        admin
      </Btn>
      <Btn active={false} onClick={() => chat.newSession("admin")}>
        new session
      </Btn>
      <span className="ml-auto self-center text-term-dim text-xs hidden sm:inline" title={me.email}>
        {me.bot_name} · {me.email}
      </span>
      <Btn active={false} onClick={doLogout} disabled={loggingOut}>
        {loggingOut ? "logging out…" : "log out"}
      </Btn>
    </div>
  );

  const drawers = (
    <>
      <ProfileDrawer open={open === "profile"} onSaved={() => void chat.newSession("admin")} />
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
