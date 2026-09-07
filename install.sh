#!/usr/bin/env bash
set -euo pipefail
umask 077

repo='stephanstarikov-hub/deckport-haupp'
version='0.2.6'

while (($#)); do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || {
        printf '%s\n' 'Missing --repo value' >&2
        exit 1
      }
      repo="$2"
      shift 2
      ;;
    --version)
      [[ $# -ge 2 ]] || {
        printf '%s\n' 'Missing --version value' >&2
        exit 1
      }
      version="${2#v}"
      shift 2
      ;;
    --help|-h)
      printf '%s\n' \
        'DeckPort VPN installer' \
        'Usage: bash install.sh [--repo OWNER/REPO] [--version 0.2.6]'
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

[[ "$repo" =~ ^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  printf '%s\n' 'Invalid GitHub repository.' >&2
  exit 1
}

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || {
  printf '%s\n' 'Invalid version.' >&2
  exit 1
}

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  printf '%s\n' 'SteamOS / Linux x86_64 is required.' >&2
  exit 1
}

for command in curl python3 pkexec id; do
  command -v "$command" >/dev/null || {
    printf 'Missing command: %s\n' "$command" >&2
    exit 1
  }
done

[[ "$(id -u)" -ne 0 ]] || {
  printf '%s\n' \
    'Run Setup from your normal Steam Deck desktop account.' >&2
  exit 1
}

work="$(mktemp -d -t deckport-install.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT

asset="deckport-vpn-${version}-payload.zip"
base="https://github.com/${repo}/releases/download/v${version}"

printf 'DeckPort VPN %s  downloading verified payload\n' "$version"

curl \
  --proto '=https' \
  --proto-redir '=https' \
  --tlsv1.2 \
  -fSL \
  --retry 2 \
  --connect-timeout 15 \
  --max-time 240 \
  "${base}/${asset}" \
  -o "$work/payload.zip"

curl \
  --proto '=https' \
  --proto-redir '=https' \
  --tlsv1.2 \
  -fsSL \
  --retry 2 \
  --connect-timeout 15 \
  --max-time 30 \
  "${base}/${asset}.sha256" \
  -o "$work/checksum"

digest="$(
python3 - "$work" "$asset" <<'PY'
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

root = Path(sys.argv[1])
asset = sys.argv[2]

parts = (root / "checksum").read_text(
    encoding="ascii"
).strip().split()

if (
    len(parts) != 2
    or parts[1] != asset
    or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0])
):
    raise SystemExit("Release checksum file is invalid.")

expected = parts[0].lower()
archive = root / "payload.zip"

with archive.open("rb") as stream:
    actual = hashlib.file_digest(
        stream,
        "sha256",
    ).hexdigest()

if actual != expected:
    raise SystemExit(
        "Release checksum verification failed; nothing installed."
    )

destination = root / "product"
destination.mkdir(mode=0o700)

required = {
    "payload.json",
    "installer/entry.py",
    "installer/transaction.py",
    "installer/bundle.py",
    "vpn/safe_fs.py",
    "vpn/ipc.py",
}

with zipfile.ZipFile(archive) as source:
    entries = source.infolist()
    names = set()

    for entry in entries:
        path = PurePosixPath(entry.filename)

        if (
            not entry.filename
            or str(path) != entry.filename
            or path.is_absolute()
            or any(part in (".", "..") for part in path.parts)
            or "\\" in entry.filename
            or ":" in entry.filename
            or any(ord(c) < 32 for c in entry.filename)
        ):
            raise SystemExit("Unsafe release archive path.")

        mode = entry.external_attr >> 16

        if (
            stat.S_IFMT(mode) != stat.S_IFREG
            or stat.S_IMODE(mode) not in (0o644, 0o755)
            or entry.filename in names
            or entry.flag_bits & 1
        ):
            raise SystemExit("Unsafe release archive entry.")

        names.add(entry.filename)

    if not required <= names:
        raise SystemExit("Incomplete DeckPort VPN payload.")

    for entry in entries:
        target = destination.joinpath(
            *PurePosixPath(entry.filename).parts
        )
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        with source.open(entry) as incoming:
            target.write_bytes(incoming.read())

        target.chmod(
            stat.S_IMODE(entry.external_attr >> 16)
        )

print(expected)
PY
)"

printf '%s\n' \
  'Payload verified. System authorization is required to install.'

pkexec \
  /usr/bin/python3 \
  -B \
  "$work/product/installer/entry.py" \
  install \
  --payload "$work/payload.zip" \
  --sha256 "$digest" \
  --decky
printf '%s\n' 'Refreshing Desktop application menu'
if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
  kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi
