import { useState } from "react";
import ChatScreen from "../components/ChatScreen";
import WelcomeGate from "../components/WelcomeGate";
import ContactModal from "../components/ContactModal";
import { useChat } from "../hooks/useChat";

export default function RecruiterPage() {
  const chat = useChat();
  const [entered, setEntered] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const ownerName = chat.config.owner_name || "the candidate";

  async function enter(name: string) {
    setEntered(true);
    await chat.connect(name);
  }

  return (
    <>
      {!entered && <WelcomeGate onEnter={enter} />}
      <ChatScreen
        title="talking about the candidate — ask me anything"
        conn={chat.conn}
        lines={chat.lines}
        busy={chat.busy}
        ready={chat.ready}
        orbState={chat.orbState}
        pulseRef={chat.pulseRef}
        onSend={chat.send}
        maxChars={chat.config.max_message_chars}
        cooldown={chat.cooldown}
        turnstileKey={chat.turnstileKey}
        onTurnstile={(t) => void chat.verify(t)}
        onTurnstileError={(m) => chat.sysLine(m, true)}
        headerAction={
          chat.ready && (
            <button
              type="button"
              onClick={() => setContactOpen(true)}
              className="shrink-0 font-mono text-[11px] px-2 py-1 rounded border border-term-line2 text-term-bright hover:border-term-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright"
            >
              leave my contact
            </button>
          )
        }
      />
      {contactOpen && (
        <ContactModal
          ownerName={ownerName}
          sessionId={chat.sessionId}
          onClose={() => setContactOpen(false)}
        />
      )}
    </>
  );
}
