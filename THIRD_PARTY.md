# Third-party software

Decky VPN plugin source: GPL-3.0-or-later. See LICENSE.

- Official Decky template, revision `90d0780e882a17f5714fc6de044c645f22608290`, BSD-3-Clause. Notice retained in `licenses/template-LICENSE`.
- sing-box 1.14.0, unmodified official linux/amd64 build, GPL-3.0-or-later with upstream additional naming condition. See `licenses/sing-box-LICENSE` and LICENSE. Decky VPN is independent and not affiliated with SagerNet. Core runs as a separate process.
- PyYAML 6.0.3, MIT, pure Python vendored in `py_modules/yaml`. Notice in `licenses/PyYAML-LICENSE`.
- @decky/api 1.1.3 and @decky/ui 4.12.0, LGPL-2.1. Notices copied into releases.
- react-icons, MIT (individual icon sets retain their own licenses); tslib, 0BSD. Notices included in releases.

- Native Desktop client uses Rust with eframe/egui 0.36.1, libc and serde_json plus their transitive dependencies. Exact versions are pinned in `desktop-native/Cargo.lock`; generated license and copyright notices are included in `licenses/rust-third-party.txt`.

Build downloads originate only from official GitHub releases, PyPI and GNU.
Subscription content cannot select executable/dependency URLs or filenames.

`decky-vpn-0.1.0-source.zip` includes this plugin's source, lockfile, build scripts,
PyYAML source and matching upstream sing-box source archive. Upstream sources:

- https://github.com/SagerNet/sing-box/tree/v1.14.0
- https://github.com/SagerNet/sing-box/releases/tag/v1.14.0
- https://sing-box.sagernet.org/installation/build-from-source/
- https://github.com/SteamDeckHomebrew/decky-plugin-template
- https://github.com/SteamDeckHomebrew/loader-api
- https://github.com/SteamDeckHomebrew/decky-frontend-lib

When redistributing binaries, provide corresponding source and notices under
their respective terms. Do not publish the binary ZIP alone without an
appropriate source distribution. See upstream go.mod/go.sum and build scripts
for the exact core build dependencies.
