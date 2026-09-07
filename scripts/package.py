import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def zip_info(name, mode):
    info = zipfile.ZipInfo(name, (2026, 9, 6, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def collect_product_files():
    files = [
        ROOT / n
        for n in (
            "main.py",
            "daemon-entry.py",
            "plugin.json",
            "package.json",
            "LICENSE",
            "README.md",
            "README.ru.md",
            "THIRD_PARTY.md",
            "install.sh",
        )
    ]

    for folder in (
        "dist",
        "vpn",
        "backend/bin",
        "py_modules/yaml",
        "licenses",
        "docs",
        "installer",
        "desktop",
        "assets",
    ):
        files.extend(
            p
            for p in (ROOT / folder).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and not p.name.startswith(".")
        )

    return sorted(set(files))


def mode_for(relative):
    if relative in {
        "backend/bin/sing-box",
        "desktop/deckport",
    }:
        return 0o755
    return 0o644


def write_v2_payload(output, version, files):
    archive = output / f"deckport-vpn-{version}-payload.zip"

    manifest_files = {}

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        manifest_files[relative] = {
            "sha256": sha256(data),
            "mode": mode_for(relative),
        }

    manifest = {
        "format": 1,
        "version": version,
        "files": manifest_files,
    }

    with zipfile.ZipFile(
        archive,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zipped:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            zipped.writestr(
                zip_info(relative, mode_for(relative)),
                path.read_bytes(),
            )

        payload = (
            json.dumps(
                manifest,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        zipped.writestr(
            zip_info("payload.json", 0o644),
            payload,
        )

    digest = sha256(archive.read_bytes())

    (output / (archive.name + ".sha256")).write_text(
        f"{digest}  {archive.name}\n",
        encoding="ascii",
    )

    return archive, digest


def write_legacy_decky_zip(output, version, files):
    archive = output / f"decky-vpn-{version}.zip"

    with zipfile.ZipFile(
        archive,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zipped:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            zipped.writestr(
                zip_info(
                    "decky-vpn/" + relative,
                    mode_for(relative),
                ),
                path.read_bytes(),
            )

    digest = sha256(archive.read_bytes())

    (output / (archive.name + ".sha256")).write_text(
        f"{digest}  {archive.name}\n",
        encoding="ascii",
    )

    return archive


def write_source(output, version):
    archive = output / f"deckport-vpn-v{version}-source.zip"

    def add_source(zipped, path, name):
        mode = 0o755 if path.name == "install.sh" else 0o644
        zipped.writestr(
            zip_info(name, mode),
            path.read_bytes(),
        )

    with zipfile.ZipFile(
        archive,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zipped:
        for name in (
            "src",
            "vpn",
            "scripts",
            "tests",
            "licenses",
            ".github",
            "docs",
            "installer",
            "desktop",
            "desktop-native",
            "assets",
        ):
            for path in sorted(
                (ROOT / name).rglob("*"),
                key=lambda item: item.as_posix(),
            ):
                relative = path.relative_to(ROOT)
                if path.is_file() and not any(
                    part in {"__pycache__", "target"}
                    for part in relative.parts
                ):
                    add_source(
                        zipped,
                        path,
                        "deckport-vpn/"
                        + relative.as_posix(),
                    )

        for name in (
            "main.py",
            "daemon-entry.py",
            "plugin.json",
            "package.json",
            "pnpm-lock.yaml",
            "rollup.config.js",
            "tsconfig.json",
            "README.md",
            "README.ru.md",
            "LICENSE",
            "THIRD_PARTY.md",
            "install.sh",
            ".gitattributes",
            ".gitignore",
        ):
            add_source(
                zipped,
                ROOT / name,
                "deckport-vpn/" + name,
            )

        for package in ("@decky/api", "@decky/ui"):
            source = ROOT / "node_modules" / package / "src"
            for path in sorted(
                source.rglob("*"),
                key=lambda item: item.as_posix(),
            ):
                if path.is_file():
                    add_source(
                        zipped,
                        path,
                        "upstream/"
                        + package
                        + "/src/"
                        + path.relative_to(source).as_posix(),
                    )

        add_source(
            zipped,
            ROOT / ".cache/sing-box-1.14.0-source.tar.gz",
            "upstream/sing-box-1.14.0-source.tar.gz",
        )
        add_source(
            zipped,
            ROOT / ".cache/pyyaml-6.0.3.tar.gz",
            "upstream/pyyaml-6.0.3.tar.gz",
        )

    return archive


def main():
    for package, filename in (
        ("@decky/api", "LICENSE"),
        ("@decky/ui", "LICENSE"),
        ("react-icons", "LICENSE"),
        ("tslib", "LICENSE.txt"),
    ):
        origin = ROOT / "node_modules" / package / filename
        if not origin.is_file():
            raise SystemExit(
                f"Missing third-party notice: {origin}"
            )

        destination = (
            ROOT
            / "licenses"
            / (
                package.replace("/", "-").replace("@", "")
                + "-LICENSE"
            )
        )
        destination.write_bytes(origin.read_bytes())

    required = (
        "dist/index.js",
        "backend/bin/sing-box",
        "py_modules/yaml/__init__.py",
        "LICENSE",
        "licenses/sing-box-LICENSE",
        "licenses/rust-third-party.txt",
        "daemon-entry.py",
        "desktop/deckport",
        "desktop/setup.py",
        "assets/deckport-vpn.svg",
        "installer/entry.py",
        "installer/bundle.py",
    )

    for name in required:
        if not (ROOT / name).is_file():
            raise SystemExit(
                f"Missing {name}: run fetch_deps.py "
                "and pnpm build first"
            )

    desktop_binary = ROOT / "desktop/deckport"

    if desktop_binary.read_bytes()[:4] != b"\x7fELF":
        raise SystemExit(
            "Desktop client is not the native Linux ELF build"
        )

    version = json.loads(
        (ROOT / "package.json").read_text(encoding="utf-8")
    )["version"]

    output = ROOT / "release"
    output.mkdir(exist_ok=True)

    files = collect_product_files()

    legacy = write_legacy_decky_zip(
        output,
        version,
        files,
    )

    payload, digest = write_v2_payload(
        output,
        version,
        files,
    )

    source = write_source(
        output,
        version,
    )

    print(
        f"Created {legacy.name}"
    )
    print(
        f"Created {payload.name} "
        f"({payload.stat().st_size / 1048576:.1f} MiB)"
    )
    print(
        f"Created {source.name} "
        f"({source.stat().st_size / 1048576:.1f} MiB)"
    )
    print(
        f"Payload SHA256 {digest}"
    )


if __name__ == "__main__":
    main()
