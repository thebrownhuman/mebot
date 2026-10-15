import { useState } from "react";
import ChatScreen from "../components/ChatScreen";
import WelcomeGate from "../components/WelcomeGate";
import { useChat } from "../hooks/useChat";

export default function RecruiterPage() {
  const chat = useChat();
  const [entered, setEntered] = useState(false);

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
      />
    </>
  );
}
