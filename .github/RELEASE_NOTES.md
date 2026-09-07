# DeckPort VPN 0.2.4

DeckPort VPN 0.2.4 is the first stable release of the native Desktop Mode client.

Highlights:

- four focused Desktop screens: VPN, Servers, Subscriptions and Settings;
- subscriptions are shared immediately between Decky and Desktop through `deckportd`;
- add, refresh, edit, delete, local-file import and pasted-text import in Desktop Mode;
- Ping All, latency display and sorting by latency or name;
- shared favorite servers, with a favorites-only filter;
- all network and IPC operations run outside the GUI thread;
- update channel, KDE autostart, safe diagnostics and Setup access;
- persistent root daemon and Unix socket IPC continue across Gaming/Desktop switches;
- bundled and checksum-pinned sing-box 1.14.0 core.

Release validation covers Python tests, TypeScript type checking, Decky frontend
build, locked Rust build and clippy, payload verification, installer rollback and
isolated Linux TUN traffic. Steam Deck LCD/OLED hardware acceptance remains a
separate manual check and is not claimed by CI.
