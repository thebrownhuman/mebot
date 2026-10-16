import { useEffect, useRef, useState } from "react";
import ChatScreen from "../components/ChatScreen";
import WelcomeGate from "../components/WelcomeGate";
import ContactModal from "../components/ContactModal";
import ContactPanel from "../components/ContactPanel";
import { useChat } from "../hooks/useChat";
import { useOwnerReplies } from "../hooks/useOwnerReplies";

export default function RecruiterPage() {
  const chat = useChat();
  const [entered, setEntered] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const ownerName = chat.config.owner_name || "the candidate";
  const { pollNow } = useOwnerReplies(chat.sessionId, chat.applyUpdates, chat.ready);

  // Right after the bot answers, check at once whether it couldn't (suggest contact).
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !chat.busy) pollNow();
    wasBusy.current = chat.busy;
  }, [chat.busy, pollNow]);

  async function enter(name: string) {
    setEntered(true);
    await chat.connect(name, { remember: true });
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
        ownerName={ownerName}
        onContact={() => setContactOpen(true)}
        headerAction={
          chat.ready && (
            <button
              type="button"
              aria-haspopup="dialog"
              onClick={() => setPanelOpen(true)}
              className="shrink-0 font-mono text-[11px] px-2 py-1 rounded border border-term-line2 text-term-bright hover:border-term-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright"
            >
              contact
            </button>
          )
        }
      />
      {panelOpen && (
        <ContactPanel
          ownerName={ownerName}
          onClose={() => setPanelOpen(false)}
          onLeave={() => {
            setPanelOpen(false);
            setContactOpen(true);
          }}
        />
      )}
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
