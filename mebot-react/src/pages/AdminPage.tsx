import { useEffect, useState } from "react";
import ChatScreen from "../components/ChatScreen";
import ProfileDrawer from "../components/ProfileDrawer";
import SessionsDrawer from "../components/SessionsDrawer";
import AdminDrawer from "../components/AdminDrawer";
import { useChat } from "../hooks/useChat";

// Light client-side gate. This obscures the panel from casual visitors who guess
// the URL; it is NOT real security (the check runs in the browser). For a public
// deployment, move auth to the backend. Change the passphrase here.
const ADMIN_PASS = "shivansh";

export default function AdminPage() {
  const chat = useChat();
  const [authed, setAuthed] = useState(false);
  const [pass, setPass] = useState("");
  const [err, setErr] = useState(false);
  const [open, setOpen] = useState<"profile" | "sessions" | "admin" | null>("admin");

  useEffect(() => {
    if (authed) void chat.connect("admin");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  if (!authed) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black px-4">
        <div className="w-full max-w-sm border border-term-line2 bg-term-panel rounded-xl p-6">
          <div className="text-term-amber text-sm mb-4">// admin access</div>
          <input
            type="password"
            value={pass}
            autoFocus
            onChange={(e) => {
              setPass(e.target.value);
              setErr(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                if (pass === ADMIN_PASS) setAuthed(true);
                else setErr(true);
              }
            }}
            placeholder="passphrase"
            className="w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright"
          />
          {err && <div className="text-term-err text-xs mt-2">nope.</div>}
          <button
            onClick={() => (pass === ADMIN_PASS ? setAuthed(true) : setErr(true))}
            className="w-full mt-4 border border-term-bright text-term-bright font-mono text-sm py-2 rounded hover:bg-term-bright/10"
          >
            enter
          </button>
        </div>
      </div>
    );
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
      title="admin — Shivansh's panel"
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
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
}) {
  return (
    <button
      onClick={onClick}
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
