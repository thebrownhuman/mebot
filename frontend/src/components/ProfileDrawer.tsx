import { useEffect, useState } from "react";
import { getProfile, saveProfile } from "../lib/api";

interface Props {
  open: boolean;
  onSaved: () => void;
}

export default function ProfileDrawer({ open, onSaved }: Props) {
  const [text, setText] = useState("loading…");
  const [note, setNote] = useState("edit the placeholders with your real info");

  useEffect(() => {
    if (open) getProfile().then(setText).catch(() => setText("(could not load profile)"));
  }, [open]);

  async function save() {
    try {
      await saveProfile(text);
      setNote("saved ✓ — applies to new messages");
      onSaved();
    } catch (e) {
      setNote("save failed: " + (e as Error).message);
    }
  }

  if (!open) return null;
  return (
    <div className="border border-term-line2 bg-term-panel/95 rounded-lg p-3 mb-3">
      <h3 className="text-xs text-term-amber tracking-wide mb-2">
        // profile — the bot answers only from this
      </h3>
      <textarea
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        className="w-full min-h-[200px] bg-term-bg text-term-fg border border-term-line2 rounded p-2.5 font-mono text-xs leading-relaxed resize-y outline-none focus:border-term-bright"
      />
      <div className="flex gap-3 items-center mt-2">
        <button
          onClick={save}
          className="border border-term-bright text-term-bright font-mono text-xs px-3.5 py-1.5 rounded hover:bg-term-bright/10"
        >
          save
        </button>
        <span className="text-term-dim text-xs">{note}</span>
      </div>
    </div>
  );
}
