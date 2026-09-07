# DeckPort VPN 0.2.9

DeckPort VPN 0.2.9 focuses on a smoother Steam Deck install/update experience, broader subscription-link handling, and a redesigned native Desktop client.

Highlights:

- automatic low-space update fallback for SteamOS systems with a small `/var`;
- the normal transactional update is still attempted first;
- on a real `ENOSPC` during an existing installation, DeckPort removes only old program files and retries the already verified payload;
- subscriptions, favorites, preferences, credentials, settings and logs are preserved because the fallback uses uninstall with `purge=False`;
- first-time installs never use the destructive low-space fallback;
- non-space filesystem errors never trigger replacement mode;
- KDE application cache is refreshed after a successful install so DeckPort VPN appears in the Desktop application menu immediately;
- generic HTTP/HTTPS provider subscription URLs are supported even when the URL has no file extension;
- pasted provider URLs and local text files containing a single provider URL are stored as URL subscriptions so Refresh/Edit keep working correctly;
- subscription detection is stricter for supported direct URI schemes and remains compatible with the existing VLESS, VMess, Trojan, Shadowsocks and SOCKS URI paths;
- native Desktop Mode client redesigned with Steam Deck-friendly dark navigation, a large Connect/Disconnect control, connection details, and clearer server/subscription/settings screens;
- native Desktop Mode client, shared daemon state, Ping All and favorites remain integrated through `deckportd`;
- bundled and checksum-pinned sing-box 1.14.0 core.

Release validation covers Python tests, TypeScript build/typecheck, locked Rust build and clippy, payload verification, rollback checks and isolated Linux TUN traffic. Steam Deck LCD/OLED hardware acceptance remains a separate manual check and is not claimed by CI.
