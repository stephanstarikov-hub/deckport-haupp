# DeckPort VPN 0.2.3

DeckPort VPN 0.2.3 is a preview release for Steam Deck.

Highlights:

- native Rust Desktop Mode client based on egui/eframe;
- Desktop Connect and Disconnect actions use the persistent system daemon;
- native Setup window for repair and uninstall;
- no PySide6 dependency is required by the native Desktop client;
- lower temporary storage requirements during upgrades;
- unchanged release files can be reused with hard links while preserving rollback;
- persistent root daemon and Unix socket IPC remain shared by Gaming Mode and Desktop Mode;
- bundled sing-box 1.14.0 core;
- Rust dependencies are pinned with Cargo.lock and third-party notices are included.

The installer verifies the release payload and SHA-256 checksum before system installation.

Validation includes Python tests, frontend type checking and build, native Rust compilation with Cargo.lock, package validation, installer tests, and isolated Linux TUN smoke testing.

This remains preview software. No kill switch or automatic reconnect is included in this release.