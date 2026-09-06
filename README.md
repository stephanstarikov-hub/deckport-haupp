<p align="center">
  <img src="docs/assets/banner.svg" alt="DeckPort VPN  Your connection. Your Deck." width="100%" />
</p>

<p align="center">
  <img alt="Platform: Steam Deck" src="https://img.shields.io/badge/Steam_Deck-Gaming_Mode-65dcb9?style=flat-square&amp;labelColor=0d1929" />
  <img alt="Core: sing-box 1.14.0" src="https://img.shields.io/badge/sing--box-1.14.0-71bfff?style=flat-square&amp;labelColor=0d1929" />
  <img alt="License: GPL 3.0 or later" src="https://img.shields.io/badge/license-GPL--3.0+-71bfff?style=flat-square&amp;labelColor=0d1929" />
  <img alt="Status: preview" src="https://img.shields.io/badge/status-preview-eec67a?style=flat-square&amp;labelColor=0d1929" />
</p>

<p align="center">
  A system-wide subscription VPN for Steam Deck, built directly into Decky Loader.<br />
  <strong>Add a subscription. Find the fastest server. Connect. Play.</strong>
</p>

<p align="center">
  <a href="#install">Install</a> 
  <a href="#subscriptions">Subscriptions</a> 
  <a href="#servers--latency">Servers</a> 
  <a href="#how-it-works">How it works</a> 
  <a href="#development">Development</a> 
  <a href="docs/DEVELOPMENT.ru.md">???????????? ?? ???????</a>
</p>

---

## VPN without leaving Gaming Mode

DeckPort VPN puts connection control, subscriptions, server selection, latency checks and public-IP verification inside the Steam Deck Quick Access Menu.

Once connected, the tunnel lives in the backend. You can close Decky, launch a game and continue using the VPN system-wide.

| Everyday use | Networking |
| :--- | :--- |
| VPN / Servers / Subscriptions interface | System-wide TUN powered by sing-box |
| URL and local-file subscriptions | IPv4 and IPv6 tunnel support |
| Search and select servers | DNS routed through the VPN |
| Ping all TCP-based servers | Backend-owned connection state |
| Sort servers by latency or name | Process monitoring and crash cleanup |
| View usage and expiry metadata | Bundled sing-box core |
| Public IP before and after VPN | No pacman or read-only SteamOS changes |

> **Preview software.** DeckPort has automated parser, installer, core configuration,
> lifecycle and isolated Linux TUN tests. Provider behavior, SteamOS releases,
> individual games and unusual network environments can still expose edge cases.

## Install

Requires:

- Steam Deck / SteamOS x86_64
- Decky Loader
- internet access for the initial installation

Run once from Konsole:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/stephanstarikov-hub/deckport-vpn/main/install.sh | bash
```

After installation, normal VPN use stays inside Gaming Mode.

The installer:

- downloads a versioned GitHub release;
- verifies its SHA-256 checksum;
- validates the archive before extraction;
- requests sudo only for installation;
- preserves saved subscriptions and settings during updates;
- keeps an installer backup of the previous plugin.

Decky Loader restarts briefly during installation or update, so an active VPN connection will be interrupted.

Prefer to inspect the installer first?

```bash
curl -fsSL https://raw.githubusercontent.com/stephanstarikov-hub/deckport-vpn/main/install.sh -o install.sh
less install.sh
bash install.sh
```

No system sing-box package and no SteamOS read-only filesystem modifications are required.

### Uninstall

Disconnect the VPN first, then run:

```bash
sudo systemctl stop plugin_loader.service
sudo rm -rf "$HOME/homebrew/plugins/decky-vpn"
sudo systemctl start plugin_loader.service
```

Saved DeckPort settings and installer backups are intentionally left untouched.

## First connection

1. Open **Decky  DeckPort VPN**.
2. Open **Subs**.
3. Add a provider URL or import a local subscription file.
4. Open **Servers**.
5. Optionally press **Ping all servers** and sort by **Fastest**.
6. Select a server.
7. Return to **VPN** and press **Connect VPN**.
8. Wait for **CONNECTED**.
9. Close Quick Access and launch your game.

The VPN page shows:

- selected server and protocol;
- connection state;
- latency when measured;
- public IP before VPN;
- current / VPN public IP;
- IP verification status.

Public-IP lookup is informational. Failure of an external IP-check service does **not** tear down an otherwise live VPN tunnel.

## Subscriptions

DeckPort supports two subscription sources.

### URL subscriptions

Add an HTTP or HTTPS provider URL directly from the Decky interface.

HTTP subscriptions are supported for providers that do not expose HTTPS, but HTTP is unencrypted in transit. Prefer HTTPS whenever your provider offers it.

URL subscriptions can be:

- refreshed;
- edited;
- deleted;
- used to select any parsed server.

### Local subscription files

You can also import a subscription without typing a long URL on the Steam Deck keyboard.

Place files in:

```text
/home/deck/homebrew/settings/decky-vpn/import/
```

Then open:

**DeckPort VPN  Subs  Local import  Scan import folder**

Supported file extensions:

```text
.txt
.conf
.json
.yaml
.yml
```

A local subscription remembers its source file. **Reload local file** reparses the same file after you replace or edit it.

For safety, DeckPort only reads files inside its dedicated import directory. Arbitrary paths, traversal such as `../`, symlinks, unsupported extensions and oversized files are rejected.

### Supported formats

Protocols:

- VLESS
- VMess
- Trojan
- Shadowsocks
- SOCKS5
- WireGuard

Formats:

- plain URI lists;
- Base64 URI lists;
- Clash YAML / JSON;
- sing-box JSON;
- single-peer WireGuard configuration.

TLS, Reality, Vision, WebSocket, gRPC and common HTTP transports are supported where applicable.

Unsupported or unsafe entries are skipped and reported in the subscription UI.

Provider-specific features such as arbitrary routing rules, local file references, external Shadowsocks plugins and insecure TLS settings are not imported.

## Servers & latency

The **Servers** page provides:

- subscription selection;
- server search;
- server selection;
- **Ping all servers**;
- sorting by **Default**, **Fastest** or **Name**.

For TCP-based protocols, DeckPort measures TCP connection latency to the actual VPN endpoint rather than ICMP ping.

WireGuard endpoints are UDP, so TCP latency is not reported for them.

Subscription endpoints resolving to private or non-global addresses are not probed.

## Connection verification

DeckPort separates **tunnel health** from **public-IP verification**.

A successful VPN connection requires the sing-box process and DeckPort TUN interface to remain alive.

The UI may additionally report:

- **Public IP changed**
- **Public IP did not change**
- **IP verification unavailable**

External IP verification failure alone does not disconnect a working tunnel.

## How it works

```text
Steam Deck Quick Access Menu
            
             typed RPC + status events
            
      Python backend
                 
                  subscription storage
                  local import directory
                  latency probes
                  public-IP verification
       
        validated node
       
   config generator
       
       
   process guardian
       
       
 bundled sing-box
       
       
  deckyvpn0 TUN
       
       
 SteamOS / games / Steam
```

The frontend does not own the VPN process.

The backend maintains connection state, and the guardian owns core lifetime and network cleanup. Closing the Quick Access Menu therefore does not disconnect an active tunnel.

Disconnect stops sing-box and removes DeckPort-owned TUN/routing state.

## Privacy & security

- Subscription credentials and URLs are excluded from public frontend subscription objects.
- Diagnostics intentionally omit provider URLs, hosts, credentials and raw sing-box output.
- Settings stay local and use restrictive filesystem permissions.
- Stored settings are **not encrypted at rest**.
- Subscription content is treated as untrusted input.
- Subscription data cannot provide shell commands.
- HTTPS certificate validation remains enabled.
- Local imports are restricted to DeckPort's dedicated import directory.
- Latency probes reject private and non-global destinations.
- There is currently **no kill switch**.
- If the VPN core stops unexpectedly, DeckPort attempts to restore ordinary networking.

## Development

Requirements:

- Node.js 22+
- pnpm 9
- Python 3.10+

```bash
pnpm install --frozen-lockfile
python scripts/fetch_deps.py
pnpm typecheck
pnpm build
python -m unittest discover -s tests -v
python scripts/check_core.py
python scripts/package.py
```

Linux integration testing:

```bash
sudo unshare --net --mount --mount-proc python3 -u scripts/linux_smoke.py
```

On Windows:

```powershell
python scripts/fetch_deps.py --windows-checker
```

### pnpm note

GitHub Actions already specifies pnpm 9.

Do not commit an automatically generated `packageManager` field to `package.json` while the workflow also supplies its own pnpm version.

## Project status

Completed:

- [x] Subscription  server  system-wide TUN
- [x] Gaming Mode connect / disconnect
- [x] HTTPS subscriptions
- [x] HTTP subscriptions
- [x] Local subscription file import
- [x] Safe local import directory
- [x] Subscription refresh / reload
- [x] Server search
- [x] TCP endpoint latency checks
- [x] Sort servers by latency or name
- [x] Public IP before / after VPN
- [x] Soft public-IP verification
- [x] Backend-owned VPN state
- [x] Crash cleanup
- [x] Verified release installer
- [x] Update backups and settings preservation

Possible future work:

- [ ] Favorites
- [ ] Automatic background latency refresh
- [ ] Auto-connect
- [ ] Retry / backoff
- [ ] Better sleep / resume handling
- [ ] Optional kill switch
- [ ] Split tunneling
- [ ] Broader provider and Steam Deck hardware validation

## Credits & license

Built using the official Decky plugin ecosystem and powered by sing-box.

Independent project; not affiliated with Valve, Steam, Steam Deck Homebrew or SagerNet.

Plugin code: [GPL-3.0-or-later](LICENSE)

Third-party dependency notices and corresponding-source information: [THIRD_PARTY.md](THIRD_PARTY.md)
