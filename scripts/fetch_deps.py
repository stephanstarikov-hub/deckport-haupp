"""Download immutable, checksum-verified upstream dependencies at build time."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.14.0"
ASSETS = {
    "linux": (f"sing-box-{VERSION}-linux-amd64.tar.gz", "2375de6999f4f56ab46b4fc5ddf26a6aba1d3e61a0f4e7ddec2f4690457d5f63"),
    "windows": (f"sing-box-{VERSION}-windows-amd64.zip", "3ffb56267da14e287be48bd10cf7e6505260125bad940b75101fbb4d5d58e5d6"),
}


def download(url, filename, expected=None):
    path = ROOT / ".cache" / filename
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url, timeout=90) as source:
            data = source.read(128 * 1024 * 1024)
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Dependency checksum mismatch")
        path.write_bytes(data)
    if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Cached dependency checksum mismatch")
    return path


def build(windows=False):
    target = ROOT / "backend" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    licenses = ROOT / "licenses"
    licenses.mkdir(exist_ok=True)
    filename, checksum = ASSETS["linux"]
    archive = download(f"https://github.com/SagerNet/sing-box/releases/download/v{VERSION}/{filename}", filename, checksum)
    with tarfile.open(archive) as tar:
        member = tar.getmember(f"sing-box-{VERSION}-linux-amd64/sing-box")
        if not member.isfile():
            raise RuntimeError("Unexpected core archive")
        (target / "sing-box").write_bytes(tar.extractfile(member).read())
    (target / "sing-box").chmod(0o755)
    yaml_archive = download("https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz", "pyyaml-6.0.3.tar.gz", "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f")
    with tarfile.open(yaml_archive) as tar:
        for member in tar.getmembers():
            prefix = "pyyaml-6.0.3/lib/yaml/"
            if member.isfile() and member.name.startswith(prefix) and member.name.endswith(".py"):
                relative = Path(member.name[len(prefix):])
                if ".." in relative.parts or relative.is_absolute():
                    raise RuntimeError("Unsafe dependency path")
                dest = ROOT / "py_modules" / "yaml" / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(tar.extractfile(member).read())
        (licenses / "PyYAML-LICENSE").write_bytes(tar.extractfile("pyyaml-6.0.3/LICENSE").read())
    source = download(f"https://codeload.github.com/SagerNet/sing-box/tar.gz/refs/tags/v{VERSION}", f"sing-box-{VERSION}-source.tar.gz")
    with tarfile.open(source) as tar:
        (licenses / "sing-box-LICENSE").write_bytes(tar.extractfile(f"sing-box-{VERSION}/LICENSE").read())
    template = download("https://raw.githubusercontent.com/SteamDeckHomebrew/decky-plugin-template/90d0780e882a17f5714fc6de044c645f22608290/LICENSE", "template-LICENSE")
    (licenses / "template-LICENSE").write_bytes(template.read_bytes())
    license_path = ROOT / "LICENSE"
    if not license_path.is_file():
        raise RuntimeError("Missing LICENSE: commit the plugin GPL-3.0-or-later text in the repo")
    if windows:
        filename, checksum = ASSETS["windows"]
        archive = download(f"https://github.com/SagerNet/sing-box/releases/download/v{VERSION}/{filename}", filename, checksum)
        with zipfile.ZipFile(archive) as zipped:
            data = zipped.read(f"sing-box-{VERSION}-windows-amd64/sing-box.exe")
        (ROOT / ".cache" / "sing-box.exe").write_bytes(data)
    print("Dependencies verified: sing-box 1.14.0 linux/amd64, PyYAML 6.0.3 (pure Python)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-checker", action="store_true")
    build(parser.parse_args().windows_checker)
