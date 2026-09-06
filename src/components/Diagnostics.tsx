import { useState } from "react";
import { ModalRoot, DialogHeader, DialogBody, DialogButton, TextField } from "@decky/ui";

export function Diagnostics({ content, closeModal }: { content: string; closeModal?: () => void }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(content); setCopied(true); }
    catch { setFailed(true); }
  };
  return <ModalRoot onCancel={closeModal} closeModal={closeModal}>
    <DialogHeader>Safe diagnostics</DialogHeader>
    <DialogBody>
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 260, overflow: "auto", fontSize: 13 }}>{content}</pre>
      <DialogButton onClick={() => void copy()}>{copied ? "Copied" : "Copy diagnostic info"}</DialogButton>
      {failed && <TextField label="Clipboard unavailable — select this text" value={content} bShowCopyAction />}
      <DialogButton onClick={closeModal}>Close</DialogButton>
    </DialogBody>
  </ModalRoot>;
}
