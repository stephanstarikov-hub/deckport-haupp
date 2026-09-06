<p align="center">
  <img src="docs/assets/banner.svg" alt="DeckPort VPN — Your connection. Your Deck." width="100%" />
</p>

<p align="center">
  <img alt="Platform: Steam Deck" src="https://img.shields.io/badge/Steam_Deck-Gaming_Mode-65dcb9?style=flat-square&amp;labelColor=0d1929" />
  <img alt="Core: sing-box 1.14.0" src="https://img.shields.io/badge/sing--box-1.14.0-71bfff?style=flat-square&amp;labelColor=0d1929" />
  <img alt="License: GPL 3.0 or later" src="https://img.shields.io/badge/license-GPL--3.0+-71bfff?style=flat-square&amp;labelColor=0d1929" />
  <img alt="Status: hardware testing pending" src="https://img.shields.io/badge/status-MVP_preview-eec67a?style=flat-square&amp;labelColor=0d1929" />
</p>

<p align="center">
  A subscription-based VPN for Steam Deck, right inside Decky Loader.<br />
  <strong>Add your subscription. Pick a server. Play.</strong>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#development">Development</a> ·
  <a href="docs/DEVELOPMENT.ru.md">Документация на русском</a>
</p>

---

## Stay in Gaming Mode

DeckPort puts your VPN subscription, server selection and connection controls
in the Steam Deck Quick Access Menu. The tunnel lives in the backend, so you
can close the menu and launch a game while it keeps running.

| Built for everyday use | Built with a real tunnel |
| :--- | :--- |
| Add, refresh and edit subscriptions | System-wide IPv4/IPv6 TUN via sing-box |
| Search servers and remember your choice | DNS through the selected VPN |
| Connect and disconnect from Decky | Backend-owned connection state |
| View subscription usage and expiry | Process monitoring and crash cleanup |
| Verify your public IP before and after | Bundled core — no pacman setup |

> **MVP preview.** Real TUN traffic and cleanup have been tested in an isolated
> Linux network. Steam Deck LCD/OLED, gamepad interaction, provider compatibility
> and SteamOS DNS/IPv6 leak testing still need hardware validation.

## Install

Requires an existing [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
installation on SteamOS x86_64. Run the installer once from Konsole; afterwards,
the normal subscription → server → Connect flow stays in Gaming Mode.

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/stephanstarikov-hub/deckport-vpn/main/install.sh | bash
```

The installer downloads a versioned release, checks its SHA-256, validates the
archive, and asks for sudo only to install it. Updating keeps a backup and
preserves subscriptions. Decky restarts briefly, disconnecting any active VPN.

Prefer to inspect first? Download [install.sh](install.sh), read it, then run:

```bash
bash install.sh
```

You can also install the release ZIP using Decky's developer installation UI.
No sing-box package installation or read-only filesystem changes are required.

### Your first connection

1. Open **Decky → DeckPort VPN**.
2. Choose **+ Add subscription**, enter a name and your provider's HTTPS URL.
3. Open **Server**, pick a node, then press **Connect**.
4. Wait for **CONNECTED**, close Quick Access and launch your game.
5. Return to DeckPort and press **Disconnect** when finished.

## Bring your subscription

**Protocols:** VLESS · VMess · Trojan · Shadowsocks · SOCKS5 · WireGuard.

**Formats:** URI lists · Base64 lists · Clash YAML/JSON · sing-box JSON ·
single-peer WireGuard configurations.

TLS, Reality, Vision, WebSocket, gRPC and basic HTTP transports are supported
where applicable. Unsupported entries are counted and skipped visibly.
Provider-specific extensions such as XHTTP, external Shadowsocks plugins,
arbitrary routing rules and insecure TLS are not imported.

SOCKS servers need UDP support for UDP games. IPv6 requires provider support;
unsupported traffic does not receive a direct fallback route.

## How it works

```text
Decky Quick Access Menu
         │ typed RPC + status events
         ▼
Python backend ── private subscription storage
         │ validated node → generated configuration
         ▼
Process guardian ── watches backend lifetime, owns cleanup
         │
         ▼
Bundled sing-box ── TUN interface ── SteamOS traffic
```

The backend checks the system route and internet access before reporting
`CONNECTED`. DNS uses the VPN. Disconnect stops the core and removes its
network state; losing the frontend does not disconnect an active tunnel.

## Privacy & recovery

- Credentials and subscription URLs stay out of public UI data and diagnostics.
- Settings are local with restrictive permissions, **not encrypted**.
- Subscription content is untrusted input; it cannot supply shell commands.
- HTTPS certificate validation stays enabled. The first VPN endpoint DNS lookup
  happens before the tunnel is established.
- **No kill switch in this preview.** A crash restores ordinary networking.
  Reconnection is manual; do not rely on this version for fail-closed privacy.

See [the technical guide](docs/DEVELOPMENT.ru.md) for routing ownership,
DNS behavior, cleanup details and a Steam Deck acceptance checklist.

## Development

Node.js 22+, pnpm 9+, Python 3.10+.

```bash
pnpm install --frozen-lockfile
python scripts/fetch_deps.py
pnpm typecheck
pnpm build
python -m unittest discover -s tests -v
python scripts/check_core.py
python scripts/package.py
```

On Windows, run `python scripts/fetch_deps.py --windows-checker` before core
validation. Linux integration testing uses an isolated network namespace:

```bash
sudo unshare --net --mount-proc python3 -u scripts/linux_smoke.py
```

This tests actual TCP traffic through TUN, Disconnect, core exit, backend-pipe
loss and guardian recovery. It refuses the host network namespace. GitHub
Actions builds and tests release artifacts.

## Roadmap

- [x] Subscription → server → system TUN → disconnect
- [x] Independent backend and crash cleanup
- [x] Verified release installer and update backups
- [ ] Steam Deck LCD/OLED hardware acceptance
- [ ] Favorites, latency tests and sorting
- [ ] Auto-connect, retry/backoff and sleep/resume recovery
- [ ] Kill switch and split tunneling after base networking is stable

## Credits & license

Built on the official [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template)
and [sing-box](https://github.com/SagerNet/sing-box).
Independent project; not affiliated with Valve, Steam Deck Homebrew or SagerNet.

Plugin code: [GPL-3.0-or-later](LICENSE). Dependency notices and source
distribution details: [THIRD_PARTY.md](THIRD_PARTY.md).
