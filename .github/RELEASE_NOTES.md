# DeckPort VPN 0.2.5

DeckPort VPN 0.2.5 focuses on making Steam Deck installation and updates painless.

Highlights:

- automatic low-space update fallback for SteamOS systems with a small `/var`;
- the normal transactional update is still attempted first;
- on a real `ENOSPC` during an existing installation, DeckPort automatically removes only old program files and retries the already verified payload;
- subscriptions, favorites, preferences, credentials, settings and logs are preserved because the fallback always uses uninstall with `purge=False`;
- first-time installs never use the destructive low-space fallback;
- non-space filesystem errors never trigger replacement mode;
- the installer refreshes the KDE application cache after a successful install so DeckPort VPN appears in the Desktop application menu immediately;
- native Desktop Mode client, shared daemon state, Ping All and favorites from 0.2.4 remain included;
- bundled and checksum-pinned sing-box 1.14.0 core.

Release validation should cover the new low-space fallback tests plus the existing
Python tests, TypeScript build/typecheck, locked Rust build and clippy, payload
verification, rollback checks and isolated Linux TUN traffic. Steam Deck LCD/OLED
hardware acceptance remains a separate manual check and is not claimed by CI.
