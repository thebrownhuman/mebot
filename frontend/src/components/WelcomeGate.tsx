import { useState } from "react";

interface Props {
  onEnter: (name: string) => void;
}

export default function WelcomeGate({ onEnter }: Props) {
  const [name, setName] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="w-full max-w-md border border-term-line2 bg-term-panel rounded-xl p-6">
        <div className="text-term-bright text-lg mb-1">Hi, I'm Anya 👋</div>
        <p className="text-term-fg text-sm leading-relaxed mb-5">
          I'm here on the candidate's behalf. Ask me anything about their background,
          experience, and projects — I'll answer in real time.
        </p>

        <label htmlFor="welcome-name" className="block text-xs text-term-dim mb-1">your name</label>
        <input
          id="welcome-name"
          value={name}
          autoFocus
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim()) onEnter(name.trim());
          }}
          placeholder="e.g. Jordan from Acme"
          className="w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright mb-4"
        />

        <label className="block text-xs text-term-dim mb-1">login credentials</label>
        <input
          disabled
          placeholder="(disabled — open access for now)"
          className="w-full bg-term-bg/50 border border-term-line rounded text-term-dim font-mono text-sm px-3 py-2 outline-none mb-5 cursor-not-allowed"
        />

        <button
          onClick={() => onEnter(name.trim() || "anonymous")}
          className="w-full border border-term-bright text-term-bright font-mono text-sm py-2.5 rounded hover:bg-term-bright/10"
        >
          start conversation
        </button>
      </div>
    </div>
  );
}
