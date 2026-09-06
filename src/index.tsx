import { useCallback, useEffect, useRef, useState } from "react";
import { addEventListener, removeEventListener, definePlugin, toaster } from "@decky/api";
import { ButtonItem, PanelSection, PanelSectionRow, DropdownItem, TextField, Focusable, showModal, ConfirmModal, staticClasses } from "@decky/ui";
import { FaShieldAlt } from "react-icons/fa";
import { api, Node, Status, Subscription } from "./api";
import { SubscriptionForm } from "./components/SubscriptionForm";
import { Diagnostics } from "./components/Diagnostics";

const errorText = (e: unknown) => e instanceof Error ? e.message : "Operation failed";
const bytes = (n: number) => `${(n / (1024 ** 3)).toFixed(1)} GB`;

function Content() {
  const [status, setStatus] = useState<Status>();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [subscriptionId, setSubscriptionId] = useState("");
  const [servers, setServers] = useState<Node[]>([]);
  const [page, setPage] = useState<"vpn" | "servers" | "subscriptions">("vpn");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(40);
  const [busy, setBusy] = useState(false);
  const [pingBusy, setPingBusy] = useState(false);
  const [pings, setPings] = useState<Record<string, { status: string; latency_ms: number | null }>>({});
  const [error, setError] = useState("");
  const operation = useRef(false);
  const latestStatus = useRef(0);
  const refresh = useCallback(async () => {
    const started = ++latestStatus.current;
    const [s, subs] = await Promise.all([api.status(), api.subscriptions()]);
    if (started === latestStatus.current) setStatus(s);
    setSubscriptions(subs);
    if (!subs.length) setPage("subscriptions");
    setSubscriptionId(id => subs.some(sub => sub.id === id) ? id : s.selected_subscription ?? subs[0]?.id ?? "");
  }, []);
  useEffect(() => {
    let active = true;
    const listener = addEventListener<[Status]>("vpn_status", s => {
      latestStatus.current++; if (active) setStatus(s);
    });
    const sync = () => { void refresh().catch(e => { if (active) setError(errorText(e)); }); };
    sync();
    // Mount fetch + event stream + polling resync after a hidden/stale QAM.
    const timer = setInterval(() => {
      const started = ++latestStatus.current;
      void api.status().then(s => { if (active && started === latestStatus.current) setStatus(s); }).catch(() => {});
    }, 3000);
    return () => { active = false; clearInterval(timer); removeEventListener("vpn_status", listener); };
  }, [refresh]);
  useEffect(() => {
    let active = true;
    setServers([]); setPings({}); setLimit(40);
    if (subscriptionId) void api.servers(subscriptionId).then(nodes => { if (active) setServers(nodes); }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [subscriptionId, subscriptions]);
  const run = async (action: () => Promise<unknown>) => {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError("");
    try { await action(); await refresh(); }
    catch (e) { setError(errorText(e)); }
    finally { operation.current = false; setBusy(false); }
  };
  const form = (subscription?: Subscription) => showModal(<SubscriptionForm subscription={subscription} done={() => { void refresh().catch(e => setError(errorText(e))); }} />);
  const selected = status?.selected_server;
  const subscription = subscriptions.find(s => s.id === subscriptionId);
  const connected = status?.state === "CONNECTED";
  const inProgress = status && ["CONNECTING", "RECONNECTING", "DISCONNECTING"].includes(status.state);
  const disconnectable = connected || inProgress || status?.state === "ERROR";
  const results = servers.filter(n => n.name.toLowerCase().includes(search.toLowerCase()));
  const goBack = () => setPage("vpn");

  return <Focusable style={{ paddingBottom: 16 }}>
    <PanelSection title="DeckPort VPN">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setPage("vpn")}>
          {page === "vpn" ? " " : ""}VPN
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setPage("servers")}>
          {page === "servers" ? " " : ""}Servers
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setPage("subscriptions")}>
          {page === "subscriptions" ? " " : ""}Subscriptions
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
    {error && <PanelSection><p role="alert" style={{ color: "#ffb2ac", overflowWrap: "anywhere" }}>{error}</p></PanelSection>}
    {page === "vpn" && <>
      <PanelSection title="Status">
        <div style={{ margin: "8px 0 16px" }}>
          <div style={{ color: connected ? "#86efac" : "#d1d5db", fontSize: 20 }}>{connected ? "●" : "○"} {status?.state.replace(/_/g, " ") ?? "Loading…"}</div>
          {status?.server && <div style={{ marginTop: 6, overflowWrap: "anywhere" }}>{status.server.name}</div>}
          {status?.error && <p style={{ color: "#ffb2ac" }}>{status.error}</p>}
        </div>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy || !status || status.state === "DISCONNECTING" || (!disconnectable && !status.selected)} onClick={() => void run(async () => {
          if (disconnectable) setStatus(await api.disconnect());
          else if (status?.selected) setStatus(await api.connect(status.selected));
        })}>{disconnectable ? (inProgress ? "CANCEL / DISCONNECT" : "DISCONNECT") : "CONNECT"}</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => setPage("servers")}>Server: {selected?.name ?? status?.server?.name ?? "Choose server"} ›</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => setPage("subscriptions")}>Subscription: {subscription?.name ?? "Add subscription"} ›</ButtonItem></PanelSectionRow>
      </PanelSection>
      <PanelSection title="IP address">
        <div style={{ marginBottom: 8 }}>
          Before VPN: {status?.before_ip ?? ""}
        </div>

        <div style={{ fontSize: 18, overflowWrap: "anywhere" }}>
          Current / VPN IP: {status?.public_ip ?? ""}
        </div>

        {connected && status?.verification === "verified" &&
          <p style={{ color: "#86efac" }}>
             VPN active  public IP changed
          </p>
        }

        {connected && status?.verification === "same_ip" &&
          <p style={{ color: "#fde68a" }}>
             Tunnel active  public IP did not change
          </p>
        }

        {connected && status?.verification === "unavailable" &&
          <p>
            VPN connected  public IP verification unavailable
          </p>
        }

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!connected || busy}
            onClick={() => void run(async () => {
              const result = await api.verify();

              toaster.toast({
                title: "DeckPort VPN",
                body: result.public_ip
                  ? `Current IP: ${result.public_ip}${result.changed ? "  IP changed" : ""}`
                  : result.tunnel_ok
                    ? "Tunnel active  IP verification unavailable"
                    : "Tunnel verification failed"
              });
            })}
          >
            Refresh / verify IP
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Diagnostics">
        <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void run(async () => {
          const [diagnostic, logs] = await Promise.all([api.diagnostic(), api.logs()]);
          showModal(<Diagnostics content={`${diagnostic}\n\n${logs}`} />);
        })}>View logs / diagnostics</ButtonItem></PanelSectionRow>
      </PanelSection>
    </>}
    {page !== "vpn" && <PanelSection><PanelSectionRow><ButtonItem layout="below" onClick={goBack}>‹ Back</ButtonItem></PanelSectionRow></PanelSection>}
    {page === "servers" && <PanelSection title="Servers">
      <PanelSectionRow><DropdownItem label="Subscription" rgOptions={subscriptions.map(s => ({ data: s.id, label: s.name }))} selectedOption={subscriptionId} onChange={o => setSubscriptionId(o.data)} /></PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={!subscriptionId || pingBusy}
          onClick={() => {
            if (!subscriptionId || pingBusy) return;

            setPingBusy(true);
            setError("");

            void api.pings(subscriptionId)
              .then(items => {
                setPings(
                  Object.fromEntries(
                    items.map(item => [item.id, item])
                  )
                );
              })
              .catch(e => setError(errorText(e)))
              .finally(() => setPingBusy(false));
          }}
        >
          {pingBusy ? "Checking servers" : "Ping all servers"}
        </ButtonItem>
      </PanelSectionRow>

      <TextField label="Search" value={search} onChange={e => { setSearch(e.target.value); setLimit(40); }} />
      {!results.length && <p>No servers. Add a subscription or clear search.</p>}
      {results.slice(0, limit).map(n => {
        const ping = pings[n.id];

        const latency = !ping
          ? "not checked"
          : ping.status === "ok"
            ? `${ping.latency_ms} ms`
            : ping.status === "unsupported"
              ? "UDP  latency unavailable"
              : ping.status === "blocked"
                ? "private endpoint blocked"
                : "timeout";

        return (
          <PanelSectionRow key={n.id}>
            <ButtonItem
              layout="below"
              disabled={busy}
              description={`${n.protocol.toUpperCase()}  ${latency}`}
              onClick={() => void run(async () => {
                await api.select(n.id);
                setPage("vpn");
              })}
            >
              {n.id === status?.selected ? " " : ""}
              {n.name}
            </ButtonItem>
          </PanelSectionRow>
        );
      })}
      {results.length > limit && <PanelSectionRow><ButtonItem layout="below" onClick={() => setLimit(limit + 40)}>Show more ({results.length - limit})</ButtonItem></PanelSectionRow>}
    </PanelSection>}
    {page === "subscriptions" && <>
      <PanelSection><PanelSectionRow><ButtonItem layout="below" onClick={() => form()}>+ Add subscription</ButtonItem></PanelSectionRow></PanelSection>
      {subscriptions.map(s => <PanelSection title={s.name} key={s.id}>
        <p>{s.count} servers · Updated {new Date(s.updated * 1000).toLocaleDateString()}</p>
        {!!s.skipped && <p>{s.skipped} unsupported or invalid entries skipped.</p>}
        {s.metadata.total !== undefined && <p>{bytes((s.metadata.upload ?? 0) + (s.metadata.download ?? 0))} / {bytes(s.metadata.total)}</p>}
        {!!s.metadata.expire && <p>Expires {new Date(s.metadata.expire * 1000).toLocaleDateString()}</p>}
        <PanelSectionRow><ButtonItem layout="below" onClick={() => { setSubscriptionId(s.id); setPage("servers"); }}>Select servers ›</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void run(() => api.refresh(s.id))}>Refresh subscription</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => form(s)}>Edit subscription</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => showModal(<ConfirmModal strTitle="Delete subscription?" strDescription="This removes the saved subscription and its servers." strOKButtonText="Delete" onOK={() => void run(() => api.delete(s.id))} />)}>Delete subscription</ButtonItem></PanelSectionRow>
      </PanelSection>)}
    </>}
  </Focusable>;
}

export default definePlugin(() => ({
  name: "DeckPort VPN",
  titleView: <div className={staticClasses.Title}>DeckPort VPN</div>,
  content: <Content />,
  icon: <FaShieldAlt />,
}));
