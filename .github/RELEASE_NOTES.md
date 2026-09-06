DeckPort VPN puts subscription-based VPN controls inside the Steam Deck Quick Access Menu.

This preview includes subscription import, server selection, Connect/Disconnect,
system TUN routing, DNS through VPN, and a bundled sing-box 1.14.0 core.

Install using `install.sh` or the attached plugin ZIP.
The shell installer verifies SHA-256 and preserves a backup when updating.
Attach the source ZIP alongside the binary ZIP when redistributing.

Validation: Python tests, TypeScript build, seven core configurations and actual
TUN traffic/cleanup in an isolated Linux namespace. Steam Deck LCD/OLED hardware
acceptance is pending. No kill switch or automatic reconnect in this preview.
