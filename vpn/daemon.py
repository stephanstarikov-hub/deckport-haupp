"""System service entry point; UI lifetime never controls this process."""
import asyncio
import json
import os
from pathlib import Path
import signal
from .ipc import Server
from .service import Service
from .storage import private_dir

BASE = Path("/var/lib/deckport-vpn")
RUNTIME = Path("/run/deckport-vpn")


async def run(root=None, base=BASE, runtime=RUNTIME):
    root = root or Path(__file__).resolve().parents[1]
    config = json.loads((base / "installation.json").read_text())
    private_dir(base / "settings")
    private_dir(runtime / "private")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)

    async def emit(*_):
        pass

    service = Service(root, base / "settings", runtime / "private", base / "logs", emit)
    service.legacy_import_dir = Path(config["home"]) / "homebrew/settings/decky-vpn/import"
    service.maintenance = (base / "transaction.json").exists()
    server = Server(service, config["uid"], runtime / "control.sock", config["gid"])
    try:
        await service.initialize()
        await server.start()
        await stopped.wait()
    finally:
        await server.close()
        await service.close(preserve_intent=True)


def main():
    os.umask(0o077)
    try:
        asyncio.run(run())
    except Exception:
        print("DeckPort service could not start; run Setup Repair", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
