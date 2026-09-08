<p align="center">
  <img src="docs/assets/banner.svg" alt="DeckPort VPN" width="100%" />
</p>

<h1 align="center">DeckPort VPN</h1>

<p align="center">
  System-wide VPN for Steam Deck with Decky Loader integration.
</p>

<p align="center">
  <a href="README.ru.md">Русский</a> ·
  <a href="#features">Features</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#development">Development</a>
</p>

<p align="center">
  <img alt="Steam Deck" src="https://img.shields.io/badge/Steam_Deck-SteamOS-1b2838?style=flat-square" />
  <img alt="Decky Loader" src="https://img.shields.io/badge/Decky_Loader-supported-1a9fff?style=flat-square" />
  <img alt="sing-box" src="https://img.shields.io/badge/sing--box-1.14.0-3aa675?style=flat-square" />
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0+-blue?style=flat-square" />
  <img alt="Status" src="https://img.shields.io/badge/status-stable-48b982?style=flat-square" />
</p>

---

## About

DeckPort VPN is an open-source VPN client designed specifically for Steam Deck.

It provides a system-wide VPN connection while keeping everyday control inside Decky Loader in Gaming Mode.

Starting with the 0.2.x architecture, the VPN process is owned by a persistent system daemon. Decky Loader and the Desktop Mode client communicate with the same local service instead of owning the VPN process themselves.

Repository: **deckport-haupp**

> DeckPort VPN 0.2.10 is the first stable Desktop release. Automated Linux coverage
> does not replace the separate LCD and OLED Steam Deck acceptance checklist.

## Features

### Gaming Mode

- Decky Loader integration
- connect and disconnect without leaving Gaming Mode
- subscription management
- server selection
- server search
- TCP latency checks
- sorting by latency or name
- favorites
- public IP before and after VPN connection
- connection state shared with the system daemon
- VPN remains active when the Decky panel is closed

### Desktop Mode

DeckPort VPN also includes a Desktop Mode client.

It communicates with the same system daemon as the Decky plugin, so subscriptions, selected server and connection state are shared between Gaming Mode and Desktop Mode.

The native Desktop client provides VPN status, subscriptions, server search,
latency checks, favorites, settings, diagnostics and Setup access.

### Supported protocols

- VLESS
- VMess
- Trojan
- Shadowsocks
- SOCKS5
- WireGuard

### Supported subscription formats

- plain URI lists
- Base64 URI lists
- Clash YAML
- Clash JSON
- sing-box JSON
- WireGuard configuration
- local `.txt` files
- local `.conf` files
- local `.json` files
- local `.yaml` files
- local `.yml` files

HTTPS subscriptions are recommended.

HTTP subscriptions are supported when required by a provider, but HTTP is not encrypted in transit.

## System architecture

DeckPort VPN 0.2.x uses a persistent system service:

- `deckportd.service`
- local Unix socket IPC
- Linux peer credential authorization
- bundled sing-box core
- system-wide TUN networking
- crash cleanup
- journaled installation transactions
- rollback support
- settings preservation during upgrades

The user interface does not own the VPN process.

Closing Decky or the Desktop application does not intentionally terminate an active VPN connection.

## Installation

### Requirements

- Steam Deck
- SteamOS x86_64
- Decky Loader for Gaming Mode integration
- internet access during installation
- a supported VPN subscription

### Install 0.2.11

Open Konsole in Desktop Mode:

```bash
curl -fL https://raw.githubusercontent.com/stephanstarikov-hub/deckport-haupp/v0.2.11/install.sh -o /tmp/deckport-install.sh
bash /tmp/deckport-install.sh --version 0.2.11
```

The installer:

1. downloads the matching versioned release payload;
2. downloads its SHA-256 checksum;
3. verifies the downloaded archive;
4. validates archive paths, file types and permissions;
5. requests system authorization;
6. installs the persistent VPN daemon;
7. installs Desktop integration;
8. installs or updates the Decky plugin;
9. preserves existing DeckPort settings where possible;
10. keeps transaction information for rollback.

No system sing-box package is required.

DeckPort VPN does not require disabling the SteamOS read-only filesystem.

## First connection

1. Open **Decky Loader**.
2. Open **DeckPort VPN**.
3. Open **Subscriptions**.
4. Add a provider URL or import a local subscription.
5. Open **Servers**.
6. Select a server.
7. Optionally run latency checks.
8. Return to the VPN page.
9. Press **Connect**.
10. Wait for the connected state.
11. Close Quick Access and launch your game.

## Subscriptions

DeckPort VPN supports remote and local subscriptions.

### URL subscriptions

Add an HTTP or HTTPS provider URL through either Decky or Desktop Mode.

Subscriptions can be:

- added
- refreshed
- edited
- deleted
- used to select parsed servers

HTTPS should be preferred whenever available.

### Local subscription files

Local subscription import is supported for:

```text
.txt
.conf
.json
.yaml
.yml
```

DeckPort validates local import paths and rejects unsafe traversal, unsupported extensions, symlinks and oversized files where applicable.

## Servers and latency

The Servers page supports:

- subscription selection
- server search
- server selection
- favorites
- TCP latency measurement
- sorting by default order
- sorting by fastest latency
- sorting by name

For TCP-based protocols, DeckPort measures connection latency to the actual VPN endpoint.

WireGuard uses UDP, so TCP latency is not reported for WireGuard endpoints.

Private and non-global destinations are rejected for public endpoint probes.

## Connection verification

DeckPort separates VPN tunnel health from external public-IP verification.

A working tunnel is not disconnected only because an external IP-check provider temporarily fails.

The interface may report:

- public IP changed
- public IP did not change
- IP verification unavailable

Public-IP verification is informational.

## Architecture

```text
                 DeckPort VPN
                      |
          +-----------+-----------+
          |                       |
    Decky Loader UI         Desktop Mode UI
     Gaming Mode                native
          |                       |
          +-----------+-----------+
                      |
                 local IPC
                      |
             deckportd.service
                root daemon
                      |
                 VPN service
                      |
              bundled sing-box
                      |
                  TUN device
                      |
               SteamOS / games
```

### IPC

Decky and Desktop clients communicate with the daemon through a local Unix socket.

The IPC layer includes:

- protocol versioning
- strict request validation
- method allowlists
- peer credential checks
- owner/root authorization
- request and response size limits
- sanitized internal errors

### VPN process ownership

The persistent daemon owns:

- connection state
- selected server
- subscription operations
- sing-box process lifetime
- generated runtime configuration
- tunnel cleanup
- diagnostics
- update maintenance state

## Security

DeckPort treats subscriptions and local files as untrusted input.

Security measures include:

- Unix socket peer credential checks
- restrictive socket permissions
- root-owned system installation
- verified release payloads
- SHA-256 manifest validation
- archive traversal protection
- symlink protection
- bounded file reads
- restrictive settings permissions
- HTTPS certificate verification
- rejection of unsafe provider destinations
- sanitized diagnostics and IPC errors

Stored settings are not encrypted at rest.

There is currently no full kill switch.

## Development

### Requirements

- Node.js 22+
- pnpm 9
- Python 3.10+

Install dependencies:

```bash
pnpm install --frozen-lockfile
python scripts/fetch_deps.py
```

Typecheck and build:

```bash
pnpm typecheck
pnpm build
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

Validate the bundled core:

```bash
python scripts/check_core.py
```

Build release packages:

```bash
python scripts/package.py
```

Linux TUN integration test:

```bash
sudo unshare --net --mount --mount-proc python3 -u scripts/linux_smoke.py
```

### pnpm note

GitHub Actions explicitly configures pnpm 9.

Do not commit an automatically generated `packageManager` field to `package.json` while the workflow also supplies its own pnpm version.

## Project status

Implemented:

- [x] persistent system VPN daemon
- [x] Decky Loader interface
- [x] system-wide TUN VPN
- [x] VLESS
- [x] VMess
- [x] Trojan
- [x] Shadowsocks
- [x] SOCKS5
- [x] WireGuard parsing
- [x] HTTPS subscriptions
- [x] HTTP subscriptions
- [x] local subscription import
- [x] subscription refresh
- [x] server search
- [x] favorites
- [x] TCP latency checks
- [x] latency sorting
- [x] public IP verification
- [x] Unix socket IPC
- [x] installer transaction journal
- [x] rollback support
- [x] release payload verification
- [x] Linux IPC integration tests
- [x] Linux TUN smoke tests
- [x] full native Desktop Mode client

Possible future work:

- [ ] improved Desktop packaging
- [ ] automatic update UX
- [ ] auto-connect
- [ ] sleep and resume improvements
- [ ] optional kill switch
- [ ] split tunneling
- [ ] broader provider testing
- [ ] broader SteamOS hardware testing

## License

DeckPort VPN is licensed under:

**GPL-3.0-or-later**

See:

- [LICENSE](LICENSE)
- [THIRD_PARTY.md](THIRD_PARTY.md)

DeckPort VPN is an independent project.

It is not affiliated with Valve, Steam, Decky Loader, Steam Deck Homebrew or SagerNet.
