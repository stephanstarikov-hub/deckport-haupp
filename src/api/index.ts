import { callable } from "@decky/api";

export type Node = { id: string; name: string; protocol: string; country: string };
export type Subscription = { id: string; name: string; count: number; updated: number; skipped: number; metadata: { upload?: number; download?: number; total?: number; expire?: number } };
export type Status = { state: "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "DISCONNECTING" | "ERROR"; server: Node | null; selected: string | null; selected_server: Node | null; selected_subscription: string | null; error: string | null; before_ip: string | null; public_ip: string | null; since: number | null };
type Result<T> = { ok: true; data: T } | { ok: false; error: string };
function rpc<A extends unknown[], T>(name: string) {
  const invoke = callable<A, Result<T>>(name);
  return async (...args: A): Promise<T> => {
    let result: Result<T>;
    try { result = await invoke(...args); }
    catch { throw new Error("Decky backend is unavailable. Reopen the plugin and try again."); }
    if (!result.ok) throw new Error(result.error);
    return result.data;
  };
}
export const api = {
  status: rpc<[], Status>("get_status"),
  subscriptions: rpc<[], Subscription[]>("get_subscriptions"),
  servers: rpc<[string], Node[]>("get_servers"),
  add: rpc<[string, string], { id: string; count: number; skipped: number }>("add_subscription"),
  refresh: rpc<[string], unknown>("update_subscription"),
  edit: rpc<[string, string, string], unknown>("edit_subscription"),
  delete: rpc<[string], boolean>("delete_subscription"),
  select: rpc<[string], Status>("select_server"),
  connect: rpc<[string], Status>("connect"),
  disconnect: rpc<[], Status>("disconnect"),
  verify: rpc<[], { verified: boolean; public_ip: string | null }>("check_connection"),
  logs: rpc<[], string>("get_logs"),
  diagnostic: rpc<[], string>("get_diagnostic_info"),
};
