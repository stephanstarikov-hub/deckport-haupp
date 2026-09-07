"""Generate notices for Rust dependencies used by the native Desktop client."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "desktop-native/Cargo.toml"
OUTPUT = ROOT / "licenses/rust-third-party.txt"

NOTICE_PREFIXES = (
    "LICENSE",
    "LICENCE",
    "COPYING",
    "NOTICE",
    "COPYRIGHT",
)


def main():
    raw = subprocess.check_output(
        [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--manifest-path",
            str(MANIFEST),
        ],
        text=True,
    )

    metadata = json.loads(raw)

    packages = sorted(
        metadata["packages"],
        key=lambda package: (
            package["name"].lower(),
            package["version"],
        ),
    )

    output = [
        "DeckPort VPN native Desktop third-party notices",
        "",
        "Generated from desktop-native/Cargo.lock.",
        "",
    ]

    for package in packages:
        if package["name"] == "deckport-vpn-desktop":
            continue

        output.append("=" * 72)
        output.append(
            f'{package["name"]} {package["version"]}'
        )
        output.append(
            f'License: {package.get("license") or "see included notice"}'
        )

        repository = package.get("repository")
        if repository:
            output.append(f"Repository: {repository}")

        root = Path(package["manifest_path"]).parent

        notices = sorted(
            path
            for path in root.iterdir()
            if path.is_file()
            and path.name.upper().startswith(NOTICE_PREFIXES)
            and path.stat().st_size <= 512 * 1024
        )

        for notice in notices:
            output.append("")
            output.append(f"--- {notice.name} ---")
            content = notice.read_text(
                encoding="utf-8",
                errors="replace",
            )
            output.append(
                "\n".join(
                    line.rstrip()
                    for line in content.splitlines()
                ).rstrip()
            )

        output.append("")

    OUTPUT.write_text(
        "\n".join(output).rstrip() + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
