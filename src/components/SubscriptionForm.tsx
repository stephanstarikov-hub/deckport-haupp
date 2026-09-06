import { useRef, useState } from "react";
import { ModalRoot, DialogHeader, DialogBody, DialogButton, TextField, Focusable } from "@decky/ui";
import { api, Subscription } from "../api";

export function SubscriptionForm({ subscription, done, closeModal }: { subscription?: Subscription; done: () => void; closeModal?: () => void }) {
  const [name, setName] = useState(subscription?.name ?? "My VPN");
  const [url, setURL] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const save = async () => {
    if (active.current) return;
    active.current = true;
    setBusy(true); setError("");
    try {
      if (subscription) await api.edit(subscription.id, name, url);
      else await api.add(url, name);
      setURL(""); done(); closeModal?.();
    } catch (e) { setError(e instanceof Error ? e.message : "Subscription could not be saved"); }
    finally { active.current = false; setBusy(false); }
  };
  return <ModalRoot onCancel={closeModal} closeModal={closeModal}>
    <DialogHeader>{subscription ? "Edit subscription" : "Add subscription"}</DialogHeader>
    <DialogBody>
      <TextField label="Name" value={name} onChange={e => setName(e.target.value)} disabled={busy} />
      <TextField label="Subscription URL" description={subscription ? "Leave blank to keep the saved URL" : "HTTP or HTTPS link from your VPN provider"} value={url} onChange={e => setURL(e.target.value)} bIsPassword disabled={busy} />
      {error && <p role="alert" style={{ color: "#ffb2ac" }}>{error}</p>}
      {busy && <p>Downloading and checking servers…</p>}
      <Focusable style={{ display: "flex", gap: 12 }}>
        <DialogButton onClick={closeModal}>Cancel</DialogButton>
        <DialogButton disabled={busy || !name.trim() || (!subscription && !url)} onClick={() => void save()}>{subscription ? "Save" : "Add"}</DialogButton>
      </Focusable>
    </DialogBody>
  </ModalRoot>;
}
