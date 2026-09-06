import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    for package, filename in (("@decky/api", "LICENSE"), ("@decky/ui", "LICENSE"), ("react-icons", "LICENSE"), ("tslib", "LICENSE.txt")):
        origin = ROOT / "node_modules" / package / filename
        if not origin.is_file():
            raise SystemExit(f"Missing third-party notice: {origin}")
        dest = ROOT / "licenses" / (package.replace("/", "-").replace("@", "") + "-LICENSE")
        dest.write_bytes(origin.read_bytes())
    required = ["dist/index.js", "backend/bin/sing-box", "py_modules/yaml/__init__.py", "LICENSE", "licenses/sing-box-LICENSE", "README.md"]
    for name in required:
        if not (ROOT / name).is_file():
            raise SystemExit(f"Missing {name}: run fetch_deps.py and pnpm build first")
    version = json.loads((ROOT / "package.json").read_text())["version"]
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    archive = output / f"decky-vpn-{version}.zip"
    files = [ROOT / n for n in ("main.py", "plugin.json", "package.json", "LICENSE", "README.md", "THIRD_PARTY.md", "install.sh")]
    for folder in ("dist", "vpn", "backend/bin", "py_modules/yaml", "licenses", "docs", "installer"):
        files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("."))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(set(files)):
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo("decky-vpn/" + rel, (2026, 9, 6, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if rel == "backend/bin/sing-box" else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + ".sha256")).write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    # Source snapshot for the plugin, including build scripts and lockfile.
    with zipfile.ZipFile(output / f"decky-vpn-{version}-source.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in ("src", "vpn", "scripts", "tests", "licenses", ".github", "docs", "installer"):
            for p in (ROOT / name).rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    zipped.write(p, "decky-vpn/" + p.relative_to(ROOT).as_posix())
        for name in ("main.py", "plugin.json", "package.json", "pnpm-lock.yaml", "rollup.config.js", "tsconfig.json", "README.md", "LICENSE", "THIRD_PARTY.md", "install.sh", ".gitattributes", ".gitignore"):
            zipped.write(ROOT / name, "decky-vpn/" + name)
        for package in ("@decky/api", "@decky/ui"):
            for p in (ROOT / "node_modules" / package / "src").rglob("*"):
                if p.is_file():
                    zipped.write(p, "upstream/" + package + "/src/" + p.relative_to(ROOT / "node_modules" / package / "src").as_posix())
        core_source = ROOT / ".cache/sing-box-1.14.0-source.tar.gz"
        zipped.write(core_source, "upstream/sing-box-1.14.0-source.tar.gz")
        zipped.write(ROOT / ".cache/pyyaml-6.0.3.tar.gz", "upstream/pyyaml-6.0.3.tar.gz")
    print(f"Created {archive.name} ({archive.stat().st_size / 1048576:.1f} MiB), SHA256 {digest}")


if __name__ == "__main__":
    main()
