## DeckPort VPN: subscription VPN in Gaming Mode

Adds a Decky plugin that imports a VPN subscription, lets the user select a node,
and runs a system TUN from a backend that survives closing Quick Access Menu.
Disconnect and process-exit cleanup restore ordinary networking.

Includes the DeckPort branding and README, modular subscription parsers,
sing-box config/process management, private storage, safe diagnostics, release
packaging and a curl installer with archive validation, backups and rollback.

### Validation

- Python parser, lifecycle, RPC and installer security/rollback tests.
- TypeScript typecheck and production Rollup build.
- Generated configurations validated by pinned sing-box 1.14.0.
- Actual TUN TCP traffic and crash cleanup in an isolated Linux namespace.

### Remaining acceptance

Steam Deck LCD/OLED, physical controller navigation, real provider connections
and SteamOS DNS/IPv6 behavior require hardware testing. Auto-connect,
auto-reconnect and kill switch are intentionally outside Phase 1.
