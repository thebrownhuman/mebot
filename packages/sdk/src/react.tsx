// React wrapper: <MebotChat botKey="pk_…" host="https://…" onReady={…} />. React is a
// peer dependency. The ref exposes open/close/toggle.
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { createMebot, type MebotInstance, type MebotOptions } from "./core";

export interface MebotChatProps extends MebotOptions {
  onReady?: () => void;
  onOpen?: () => void;
  onClose?: () => void;
  onMessage?: (detail: { role: string }) => void;
}

export interface MebotChatHandle {
  open(): void;
  close(): void;
  toggle(): void;
}

export const MebotChat = forwardRef<MebotChatHandle, MebotChatProps>(function MebotChat(props, ref) {
  const inst = useRef<MebotInstance | null>(null);
  const cbs = useRef(props);
  cbs.current = props;
  const { onReady, onOpen, onClose, onMessage, ...opts } = props;
  void onReady, onOpen, onClose, onMessage;
  const key = JSON.stringify(opts);

  useEffect(() => {
    const i = createMebot(JSON.parse(key) as MebotOptions);
    inst.current = i;
    i.on("ready", () => cbs.current.onReady?.());
    i.on("open", () => cbs.current.onOpen?.());
    i.on("close", () => cbs.current.onClose?.());
    i.on("message", (d) => cbs.current.onMessage?.(d as { role: string }));
    return () => {
      i.destroy();
      inst.current = null;
    };
  }, [key]);

  useImperativeHandle(ref, () => ({
    open: () => inst.current?.open(),
    close: () => inst.current?.close(),
    toggle: () => inst.current?.toggle(),
  }));
  return null;
});
