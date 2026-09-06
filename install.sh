#!/usr/bin/env bash
set -euo pipefail
umask 077

repo='stephanstarikov-hub/deckport-vpn'
version='0.1.3'
while (($#)); do
  case "$1" in
    --repo) [[ $# -ge 2 ]] || { printf '%s\n' 'Missing --repo value' >&2; exit 1; }; repo="$2"; shift 2 ;;
    --version) [[ $# -ge 2 ]] || { printf '%s\n' 'Missing --version value' >&2; exit 1; }; version="${2#v}"; shift 2 ;;
    --help|-h) printf '%s\n' 'DeckPort VPN installer' 'Usage: bash install.sh [--repo OWNER/REPO] [--version 0.1.0]' 'Requires SteamOS x86_64 and an existing Decky installation.'; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done
[[ "$repo" =~ ^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { printf '%s\n' 'Invalid GitHub repository.' >&2; exit 1; }
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || { printf '%s\n' 'Invalid version.' >&2; exit 1; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { printf '%s\n' 'SteamOS / Linux x86_64 is required.' >&2; exit 1; }
for command in curl python3 sudo getent; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done
account="${SUDO_USER:-${USER:-}}"
[[ -n "$account" && "$account" != root ]] || { printf '%s\n' 'Run the installer from your normal Steam Deck user account.' >&2; exit 1; }
user_home="$(getent passwd "$account" | cut -d: -f6)"
[[ "$user_home" == /* && -d "$user_home/homebrew/plugins" && -f "$user_home/homebrew/services/PluginLoader" ]] || { printf '%s\n' 'Decky Loader was not found in your homebrew directory. Install Decky first.' >&2; exit 1; }
work="$(mktemp -d -t deckport-install.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
asset="decky-vpn-${version}.zip"
base="https://github.com/${repo}/releases/download/v${version}"
printf 'DeckPort VPN %s — downloading from %s\n' "$version" "$repo"
curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fSL --retry 2 --connect-timeout 15 --max-time 180 "${base}/${asset}" -o "$work/bundle.zip"
curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL --retry 2 --connect-timeout 15 --max-time 30 "${base}/${asset}.sha256" -o "$work/checksum"
# Verify before extracting or executing the privileged installer.
python3 - "$work" <<'PY'
import hashlib, pathlib, re, sys, zipfile
root = pathlib.Path(sys.argv[1])
digest = (root / 'checksum').read_text().split()[0]
if not re.fullmatch(r'[0-9a-fA-F]{64}', digest) or hashlib.sha256((root / 'bundle.zip').read_bytes()).hexdigest() != digest.lower():
    raise SystemExit('Release checksum verification failed; nothing installed.')
with zipfile.ZipFile(root / 'bundle.zip') as archive:
    helper = archive.read('decky-vpn/installer/apply.py')
    if len(helper) > 65536:
        raise SystemExit('Unexpected installer size')
    (root / 'apply.py').write_bytes(helper)
PY
printf '%s\n' 'Checksum verified. Installing will briefly restart Decky and disconnect VPN.'
sudo -- python3 "$work/apply.py" "$work/bundle.zip" "$work/checksum" "$user_home/homebrew"
