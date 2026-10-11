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
        title="talking about Shivansh — ask me anything"
        conn={chat.conn}
        lines={chat.lines}
        busy={chat.busy}
        ready={chat.ready}
        orbState={chat.orbState}
        pulseRef={chat.pulseRef}
        onSend={chat.send}
      />
    </>
  );
}
