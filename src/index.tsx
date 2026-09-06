import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addEventListener,
  removeEventListener,
  definePlugin,
  toaster,
} from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DialogBody,
  DialogButton,
  DialogHeader,
  DropdownItem,
  Focusable,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  TextField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { FaShieldAlt } from "react-icons/fa";
import {
  api,
  ImportFile,
  Node,
  Status,
  Subscription,
} from "./api";
import { SubscriptionForm } from "./components/SubscriptionForm";
import { Diagnostics } from "./components/Diagnostics";

const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Operation failed";

const bytes = (n: number) =>
  `${(n / (1024 ** 3)).toFixed(1)} GB`;

const fileSize = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 ** 2)).toFixed(1)} MB`;
};

function ImportFileModal({
  file,
  done,
  closeModal,
}: {
  file: ImportFile;
  done: () => void;
  closeModal?: () => void;
}) {
  const defaultName = file.name.replace(/\.[^.]+$/, "") || "Local VPN";
  const [name, setName] = useState(defaultName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (busy || !name.trim()) return;

    setBusy(true);
    setError("");

    try {
      const result = await api.importFile(file.name, name.trim());

      toaster.toast({
        title: "DeckPort VPN",
        body: `Imported ${result.count} servers`,
      });

      done();
      closeModal?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>Import subscription</DialogHeader>

      <DialogBody>
        <p style={{ overflowWrap: "anywhere", opacity: 0.8 }}>
          {file.name}
        </p>

        <TextField
          label="Subscription name"
          value={name}
          disabled={busy}
          onChange={e => setName(e.target.value)}
        />

        {error && (
          <p role="alert" style={{ color: "#ffb2ac" }}>
            {error}
          </p>
        )}

        {busy && <p>Reading and checking servers</p>}

        <Focusable style={{ display: "flex", gap: 12 }}>
          <DialogButton onClick={closeModal}>
            Cancel
          </DialogButton>

          <DialogButton
            disabled={busy || !name.trim()}
            onClick={() => void save()}
          >
            Import
          </DialogButton>
        </Focusable>
      </DialogBody>
    </ModalRoot>
  );
}

function Content() {
  const [status, setStatus] = useState<Status>();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [subscriptionId, setSubscriptionId] = useState("");
  const [servers, setServers] = useState<Node[]>([]);
  const [page, setPage] = useState<"vpn" | "servers" | "subscriptions">("vpn");

  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(40);
  const [sortMode, setSortMode] =
    useState<"default" | "latency" | "name">("default");

  const [busy, setBusy] = useState(false);
  const [pingBusy, setPingBusy] = useState(false);
  const [pings, setPings] = useState<
    Record<string, { status: string; latency_ms: number | null }>
  >({});

  const [importFiles, setImportFiles] = useState<ImportFile[]>([]);
  const [importBusy, setImportBusy] = useState(false);

  const [error, setError] = useState("");

  const operation = useRef(false);
  const latestStatus = useRef(0);

  const refresh = useCallback(async () => {
    const started = ++latestStatus.current;

    const [s, subs] = await Promise.all([
      api.status(),
      api.subscriptions(),
    ]);

    if (started === latestStatus.current) {
      setStatus(s);
    }

    setSubscriptions(subs);

    if (!subs.length) {
      setPage("subscriptions");
    }

    setSubscriptionId(id =>
      subs.some(sub => sub.id === id)
        ? id
        : s.selected_subscription ?? subs[0]?.id ?? ""
    );
  }, []);

  const refreshImportFiles = useCallback(async () => {
    setImportBusy(true);

    try {
      setImportFiles(await api.importFiles());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setImportBusy(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    const listener = addEventListener<[Status]>(
      "vpn_status",
      s => {
        latestStatus.current++;
        if (active) setStatus(s);
      }
    );

    const sync = () => {
      void refresh().catch(e => {
        if (active) setError(errorText(e));
      });
    };

    sync();

    const timer = setInterval(() => {
      const started = ++latestStatus.current;

      void api
        .status()
        .then(s => {
          if (active && started === latestStatus.current) {
            setStatus(s);
          }
        })
        .catch(() => {});
    }, 3000);

    return () => {
      active = false;
      clearInterval(timer);
      removeEventListener("vpn_status", listener);
    };
  }, [refresh]);

  useEffect(() => {
    let active = true;

    setServers([]);
    setPings({});
    setLimit(40);

    if (subscriptionId) {
      void api
        .servers(subscriptionId)
        .then(nodes => {
          if (active) setServers(nodes);
        })
        .catch(e => {
          if (active) setError(errorText(e));
        });
    }

    return () => {
      active = false;
    };
  }, [subscriptionId, subscriptions]);

  useEffect(() => {
    if (page === "subscriptions") {
      void refreshImportFiles();
    }
  }, [page, refreshImportFiles]);

  const run = async (action: () => Promise<unknown>) => {
    if (operation.current) return;

    operation.current = true;
    setBusy(true);
    setError("");

    try {
      await action();
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };

  const form = (subscription?: Subscription) =>
    showModal(
      <SubscriptionForm
        subscription={subscription}
        done={() => {
          void refresh().catch(e => setError(errorText(e)));
        }}
      />
    );

  const subscription = subscriptions.find(
    s => s.id === subscriptionId
  );

  const selected =
    status?.selected_server ?? status?.server;

  const connected =
    status?.state === "CONNECTED";

  const inProgress =
    status &&
    ["CONNECTING", "RECONNECTING", "DISCONNECTING"].includes(
      status.state
    );

  const disconnectable =
    connected ||
    inProgress ||
    status?.state === "ERROR";

  const selectedPing =
    selected ? pings[selected.id] : undefined;

  const selectedLatency =
    selectedPing?.status === "ok"
      ? `${selectedPing.latency_ms} ms`
      : undefined;

  const statusText =
    status?.state.replace(/_/g, " ") ?? "Loading";

  const verificationText =
    status?.verification === "verified"
      ? "Public IP changed"
      : status?.verification === "same_ip"
        ? "Public IP did not change"
        : status?.verification === "unavailable"
          ? "IP verification unavailable"
          : "";

  const verificationColor =
    status?.verification === "verified"
      ? "#86efac"
      : status?.verification === "same_ip"
        ? "#fde68a"
        : "#d1d5db";

  const visibleServers = useMemo(() => {
    const filtered = servers.filter(n =>
      n.name.toLowerCase().includes(search.toLowerCase())
    );

    if (sortMode === "name") {
      return [...filtered].sort((a, b) =>
        a.name.localeCompare(b.name)
      );
    }

    if (sortMode === "latency") {
      return [...filtered].sort((a, b) => {
        const pa = pings[a.id];
        const pb = pings[b.id];

        const va =
          pa?.status === "ok" && pa.latency_ms !== null
            ? pa.latency_ms
            : Number.MAX_SAFE_INTEGER;

        const vb =
          pb?.status === "ok" && pb.latency_ms !== null
            ? pb.latency_ms
            : Number.MAX_SAFE_INTEGER;

        return va - vb;
      });
    }

    return filtered;
  }, [servers, search, sortMode, pings]);

  const pingAll = () => {
    if (!subscriptionId || pingBusy) return;

    setPingBusy(true);
    setError("");

    void api
      .pings(subscriptionId)
      .then(items => {
        setPings(
          Object.fromEntries(
            items.map(item => [item.id, item])
          )
        );

        setSortMode("latency");
      })
      .catch(e => setError(errorText(e)))
      .finally(() => setPingBusy(false));
  };

  return (
    <Focusable style={{ paddingBottom: 18 }}>
      <PanelSection>
        <div
          style={{
            padding: "6px 4px 12px",
          }}
        >
          <div
            style={{
              fontSize: 24,
              fontWeight: 700,
              marginBottom: 3,
            }}
          >
            DeckPort VPN
          </div>

          <div style={{ opacity: 0.65, fontSize: 12 }}>
            System-wide VPN for Steam Deck
          </div>
        </div>

        <Focusable
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 6,
            marginTop: 10,
            padding: "0 2px",
          }}
        >
          {[
            ["vpn", "VPN"],
            ["servers", "Servers"],
            ["subscriptions", "Subs"],
          ].map(([key, label]) => {
            const active = page === key;

            return (
              <div
                key={key}
                onClick={() =>
                  setPage(
                    key as "vpn" | "servers" | "subscriptions"
                  )
                }
                style={{
                  flex: 1,
                  minWidth: 0,
                  textAlign: "center",
                  padding: "8px 4px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: active ? 700 : 500,
                  opacity: active ? 1 : 0.6,
                  background: active
                    ? "rgba(255,255,255,0.10)"
                    : "transparent",
                  borderBottom: active
                    ? "2px solid rgba(255,255,255,0.85)"
                    : "2px solid transparent",
                }}
              >
                {label}
              </div>
            );
          })}
        </Focusable>
      </PanelSection>

      {error && (
        <PanelSection>
          <div
            role="alert"
            style={{
              color: "#ffb2ac",
              overflowWrap: "anywhere",
              padding: 8,
            }}
          >
            {error}
          </div>
        </PanelSection>
      )}

      {page === "vpn" && (
        <>
          <PanelSection>
            <div
              style={{
                padding: "14px 12px",
                borderRadius: 12,
                background: "rgba(255,255,255,0.06)",
              }}
            >
              <div
                style={{
                  fontSize: 13,
                  opacity: 0.65,
                  marginBottom: 5,
                }}
              >
                VPN STATUS
              </div>

              <div
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: connected
                    ? "#86efac"
                    : inProgress
                      ? "#fde68a"
                      : "#d1d5db",
                }}
              >
                {connected ? " " : inProgress ? " " : " "}
                {statusText}
              </div>

              {selected && (
                <div style={{ marginTop: 14 }}>
                  <div
                    style={{
                      fontSize: 18,
                      fontWeight: 600,
                      overflowWrap: "anywhere",
                    }}
                  >
                    {selected.name}
                  </div>

                  <div
                    style={{
                      opacity: 0.65,
                      marginTop: 3,
                    }}
                  >
                    {selected.protocol.toUpperCase()}
                    {selectedLatency
                      ? `    ${selectedLatency}`
                      : ""}
                  </div>
                </div>
              )}

              {connected && verificationText && (
                <div
                  style={{
                    marginTop: 12,
                    color: verificationColor,
                  }}
                >
                   {verificationText}
                </div>
              )}

              {status?.error && (
                <div
                  style={{
                    marginTop: 12,
                    color: "#ffb2ac",
                  }}
                >
                  {status.error}
                </div>
              )}
            </div>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={
                  busy ||
                  !status ||
                  status.state === "DISCONNECTING" ||
                  (!disconnectable && !status.selected)
                }
                onClick={() =>
                  void run(async () => {
                    if (disconnectable) {
                      setStatus(await api.disconnect());
                    } else if (status?.selected) {
                      setStatus(
                        await api.connect(status.selected)
                      );
                    }
                  })
                }
              >
                {disconnectable
                  ? inProgress
                    ? "CANCEL / DISCONNECT"
                    : "DISCONNECT VPN"
                  : "CONNECT VPN"}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Connection">
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => setPage("servers")}
                description={
                  selectedLatency
                    ? `${selected?.protocol.toUpperCase()}  ${selectedLatency}`
                    : selected?.protocol.toUpperCase()
                }
              >
                {selected?.name ?? "Choose server"}
              </ButtonItem>
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => setPage("subscriptions")}
                description={
                  subscription
                    ? `${subscription.count} servers`
                    : undefined
                }
              >
                {subscription?.name ?? "Add subscription"}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="IP">
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 10,
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  padding: 10,
                  borderRadius: 10,
                  background: "rgba(255,255,255,0.05)",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    opacity: 0.55,
                    marginBottom: 4,
                  }}
                >
                  BEFORE VPN
                </div>

                <div style={{ overflowWrap: "anywhere" }}>
                  {status?.before_ip || ""}
                </div>
              </div>

              <div
                style={{
                  padding: 10,
                  borderRadius: 10,
                  background: "rgba(255,255,255,0.05)",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    opacity: 0.55,
                    marginBottom: 4,
                  }}
                >
                  VPN / CURRENT
                </div>

                <div style={{ overflowWrap: "anywhere" }}>
                  {status?.public_ip || ""}
                </div>
              </div>
            </div>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={!connected || busy}
                onClick={() =>
                  void run(async () => {
                    const result = await api.verify();

                    toaster.toast({
                      title: "DeckPort VPN",
                      body: result.public_ip
                        ? `Current IP: ${result.public_ip}${
                            result.changed
                              ? "  IP changed"
                              : ""
                          }`
                        : result.tunnel_ok
                          ? "Tunnel active  IP verification unavailable"
                          : "Tunnel verification failed",
                    });
                  })
                }
              >
                Refresh IP
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Tools">
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const [diagnostic, logs] =
                      await Promise.all([
                        api.diagnostic(),
                        api.logs(),
                      ]);

                    showModal(
                      <Diagnostics
                        content={`${diagnostic}\n\n${logs}`}
                      />
                    );
                  })
                }
              >
                Logs / diagnostics
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </>
      )}

      {page === "servers" && (
        <>
          <PanelSection title="Server browser">
            <PanelSectionRow>
              <DropdownItem
                label="Subscription"
                rgOptions={subscriptions.map(s => ({
                  data: s.id,
                  label: s.name,
                }))}
                selectedOption={subscriptionId}
                onChange={o => setSubscriptionId(o.data)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <DropdownItem
                label="Sort"
                rgOptions={[
                  {
                    data: "default",
                    label: "Default",
                  },
                  {
                    data: "latency",
                    label: "Fastest",
                  },
                  {
                    data: "name",
                    label: "Name",
                  },
                ]}
                selectedOption={sortMode}
                onChange={o =>
                  setSortMode(
                    o.data as
                      | "default"
                      | "latency"
                      | "name"
                  )
                }
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={!subscriptionId || pingBusy}
                onClick={pingAll}
              >
                {pingBusy
                  ? "Checking servers"
                  : " Ping all servers"}
              </ButtonItem>
            </PanelSectionRow>

            <TextField
              label="Search"
              value={search}
              onChange={e => {
                setSearch(e.target.value);
                setLimit(40);
              }}
            />
          </PanelSection>

          <PanelSection
            title={`Servers (${visibleServers.length})`}
          >
            {!visibleServers.length && (
              <p>
                No servers. Add a subscription or clear
                search.
              </p>
            )}

            {visibleServers
              .slice(0, limit)
              .map(n => {
                const ping = pings[n.id];

                const latency =
                  !ping
                    ? "Not checked"
                    : ping.status === "ok"
                      ? `${ping.latency_ms} ms`
                      : ping.status === "unsupported"
                        ? "UDP latency unavailable"
                        : ping.status === "blocked"
                          ? "Private endpoint blocked"
                          : "Timeout";

                return (
                  <PanelSectionRow key={n.id}>
                    <ButtonItem
                      layout="below"
                      disabled={busy}
                      description={`${n.protocol.toUpperCase()}  ${latency}`}
                      onClick={() =>
                        void run(async () => {
                          await api.select(n.id);
                          setPage("vpn");
                        })
                      }
                    >
                      {n.id === status?.selected
                        ? " "
                        : ""}
                      {n.name}
                    </ButtonItem>
                  </PanelSectionRow>
                );
              })}

            {visibleServers.length > limit && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() =>
                    setLimit(limit + 40)
                  }
                >
                  Show more (
                  {visibleServers.length - limit})
                </ButtonItem>
              </PanelSectionRow>
            )}
          </PanelSection>
        </>
      )}

      {page === "subscriptions" && (
        <>
          <PanelSection title="Add subscription">
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                description="HTTP or HTTPS provider link"
                onClick={() => form()}
              >
                + Add from URL
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          <PanelSection title="Local import">
            <div
              style={{
                padding: "4px 8px 12px",
                opacity: 0.7,
                fontSize: 12,
                overflowWrap: "anywhere",
              }}
            >
              Put subscription files in:
              <br />
              /home/deck/homebrew/settings/decky-vpn/import/
            </div>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={importBusy}
                onClick={() =>
                  void refreshImportFiles()
                }
              >
                {importBusy
                  ? "Scanning"
                  : " Scan import folder"}
              </ButtonItem>
            </PanelSectionRow>

            {!importBusy && !importFiles.length && (
              <div
                style={{
                  padding: 8,
                  opacity: 0.65,
                }}
              >
                No import files found.
              </div>
            )}

            {importFiles.map(file => (
              <PanelSectionRow key={file.name}>
                <ButtonItem
                  layout="below"
                  description={`${fileSize(
                    file.size
                  )}  ${new Date(
                    file.modified * 1000
                  ).toLocaleDateString()}`}
                  onClick={() =>
                    showModal(
                      <ImportFileModal
                        file={file}
                        done={() => {
                          void Promise.all([
                            refresh(),
                            refreshImportFiles(),
                          ]).catch(e =>
                            setError(errorText(e))
                          );
                        }}
                      />
                    )
                  }
                >
                  Import  {file.name}
                </ButtonItem>
              </PanelSectionRow>
            ))}
          </PanelSection>

          <PanelSection title={`Subscriptions (${subscriptions.length})`}>
            {!subscriptions.length && (
              <div style={{ padding: 8, opacity: 0.7 }}>
                Add a URL or import a local file to get
                started.
              </div>
            )}
          </PanelSection>

          {subscriptions.map(s => (
            <PanelSection title={s.name} key={s.id}>
              <div
                style={{
                  padding: "4px 8px 10px",
                  opacity: 0.75,
                }}
              >
                {s.count} servers
                {"  "}
                {s.source_type === "file"
                  ? `Local file: ${s.source_label}`
                  : "URL subscription"}
                <br />
                Updated{" "}
                {new Date(
                  s.updated * 1000
                ).toLocaleDateString()}
              </div>

              {!!s.skipped && (
                <p>
                  {s.skipped} unsupported or invalid
                  entries skipped.
                </p>
              )}

              {s.metadata.total !== undefined && (
                <p>
                  {bytes(
                    (s.metadata.upload ?? 0) +
                      (s.metadata.download ?? 0)
                  )}{" "}
                  / {bytes(s.metadata.total)}
                </p>
              )}

              {!!s.metadata.expire && (
                <p>
                  Expires{" "}
                  {new Date(
                    s.metadata.expire * 1000
                  ).toLocaleDateString()}
                </p>
              )}

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() => {
                    setSubscriptionId(s.id);
                    setPage("servers");
                  }}
                >
                  Browse servers
                </ButtonItem>
              </PanelSectionRow>

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      api.refresh(s.id)
                    )
                  }
                >
                  {s.source_type === "file"
                    ? "Reload local file"
                    : "Refresh subscription"}
                </ButtonItem>
              </PanelSectionRow>

              {s.source_type === "url" && (
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    disabled={busy}
                    onClick={() => form(s)}
                  >
                    Edit subscription
                  </ButtonItem>
                </PanelSectionRow>
              )}

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy}
                  onClick={() =>
                    showModal(
                      <ConfirmModal
                        strTitle="Delete subscription?"
                        strDescription="This removes the saved subscription and its servers."
                        strOKButtonText="Delete"
                        onOK={() =>
                          void run(() =>
                            api.delete(s.id)
                          )
                        }
                      />
                    )
                  }
                >
                  Delete subscription
                </ButtonItem>
              </PanelSectionRow>
            </PanelSection>
          ))}
        </>
      )}
    </Focusable>
  );
}

export default definePlugin(() => ({
  name: "DeckPort VPN",
  titleView: (
    <div className={staticClasses.Title}>
      DeckPort VPN
    </div>
  ),
  content: <Content />,
  icon: <FaShieldAlt />,
}));
