# Native Desktop interface

The Desktop UI uses the existing Rust/egui application and the existing daemon
API. The reference-inspired theme is in `desktop-native/src/theme.rs`; no web
wrapper, image downloads or new dependencies are required.

## Run on Linux / Steam Deck Desktop Mode

From this checkout, with the native build dependencies from CI installed:

```bash
cargo run --manifest-path desktop-native/Cargo.toml --locked
```

This opens the updated interface without replacing the installed application.
The daemon and an existing subscription are needed for real VPN operations.
Without the daemon, Home shows **Core unavailable** and does not claim that the
VPN is connected. Opening the interface does not automatically connect the VPN.

## Check

```bash
cargo fmt --manifest-path desktop-native/Cargo.toml -- --check
cargo clippy --manifest-path desktop-native/Cargo.toml --locked -- -D warnings
cargo test --manifest-path desktop-native/Cargo.toml --locked
```

The native tests exercise connection labels, power-button actions, uptime,
active/selected-server presentation, daemon loss, and all four views at both
1280 × 760 and 800 × 560. Rendering tests use an offline egui context without
connecting to the VPN service or changing preferences.

## Visual acceptance

- Home: dark sidebar, vector icons, dotted world backdrop, green connected ring,
  server selector, uptime/protocol/latency strip and connection side cards.
- Servers: search, sorting, subscription selection, selected row and independent
  favorite controls; long server names have tooltips.
- Subscriptions: private-source cards, counts, refresh controls and the existing
  add/import/edit/delete flows; provider URLs remain masked.
- Settings: card groups, real Desktop autostart toggle, update channel, Setup
  and safe diagnostics.
- Check keyboard navigation and the stacked Home layout at the minimum width.
- Check connected, disconnected, transitional, error and daemon-unavailable
  states against the real service before release.

Auto Connect and Kill Switch are explicitly disabled and marked unsupported,
because the current daemon does not implement them. The dashboard shows real
uptime, protocol and measured TCP latency instead of invented traffic counters.
Country badges use provided ISO codes, falling back to a globe; the decorative
map does not assert server geolocation. Native window controls are preserved.

Release builds run the native tests, formatting, clippy and the existing product
checks in GitHub Actions. Native graphical acceptance on Steam Deck LCD/OLED
remains a separate manual check; it is not implied by the automated build.
