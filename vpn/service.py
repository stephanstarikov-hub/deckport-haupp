import asyncio
import copy
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
import uuid
from .core.config import generate, CORE_VERSION
from .core.process import Core
from .errors import VPNError
from .network import public_ip
from .storage import Store, private_dir, atomic_json
from .subscription.fetch import download, validate_url
from .subscription.model import public_node
from .subscription.parser import parse


class Service:
    def __init__(self, root, settings, runtime, logs, emit):
        for p in (settings, runtime, logs):
            private_dir(p)
        self.store = Store(settings / "subscriptions.json")
        self.runtime, self.logs, self.emit = runtime, logs, emit
        self.core = Core(root, runtime)
        self.state = {"state": "DISCONNECTED", "server": None, "selected": self.store.data["selected"], "error": None, "before_ip": None, "public_ip": None, "since": None}
        self.lock = asyncio.Lock()
        self.download_lock = asyncio.Lock()
        self.task = None
        self.monitor = None
        self.closing = False
        self.logger = logging.getLogger("decky-vpn-safe")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(logs / "plugin.log", maxBytes=128 * 1024, backupCount=2, encoding="utf-8")
        self.logger.addHandler(handler)
        self.log_handler = handler

    async def initialize(self):
        try:
            await self.core.recover()
        except VPNError as e:
            await self.set_state("ERROR", error=str(e))
        self.monitor = asyncio.create_task(self.watch())

    async def set_state(self, state, **kwargs):
        self.state.update(state=state, **kwargs)
        self.logger.info("State: %s", state)
        atomic_json(self.runtime / "state.json", self.state)
        try:
            await asyncio.wait_for(self.emit("vpn_status", self.status()), 2)
        except Exception:
            pass

    def status(self):
        result = copy.deepcopy(self.state)
        result.update(selected_server=None, selected_subscription=None)
        for subscription in self.store.data["subscriptions"]:
            for n in subscription["nodes"]:
                if n["id"] == self.state["selected"]:
                    result.update(selected_server=public_node(n), selected_subscription=subscription["id"])
        return result

    def subscriptions(self):
        return [{"id": s["id"], "name": s["name"], "count": len(s["nodes"]), "updated": s["updated"], "metadata": s["metadata"], "skipped": s["skipped"]} for s in self.store.data["subscriptions"]]

    def find_subscription(self, identifier):
        self.validate_id(identifier)
        result = next((s for s in self.store.data["subscriptions"] if s["id"] == identifier), None)
        if result is None:
            raise VPNError("Subscription not found")
        return result

    @staticmethod
    def validate_id(value):
        if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise VPNError("Invalid identifier")

    def find_node(self, identifier):
        self.validate_id(identifier)
        for s in self.store.data["subscriptions"]:
            for n in s["nodes"]:
                if n["id"] == identifier:
                    return n
        raise VPNError("Server not found; refresh the server list")

    def servers(self, subscription_id):
        return [public_node(n) for n in self.find_subscription(subscription_id)["nodes"]]

    async def add_or_update(self, url, name, identifier=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name) or "://" in name:
            raise VPNError("Subscription name must contain 1–80 characters")
        editing = identifier is not None
        if identifier:
            self.find_subscription(identifier)
        elif len(self.store.data["subscriptions"]) >= 30:
            raise VPNError("Subscription limit reached (30)")
        validate_url(url)
        if self.download_lock.locked():
            raise VPNError("A subscription download is already running")
        identifier = identifier or uuid.uuid4().hex
        async with self.download_lock:
            try:
                # Bounded sockets and body size; no shell, proxy env, or recursive config fetching.
                text, metadata = await asyncio.wait_for(asyncio.to_thread(download, url), 30)
                nodes, skipped = await asyncio.wait_for(asyncio.to_thread(parse, text, identifier), 10)
            except asyncio.TimeoutError:
                raise VPNError("Subscription download or parsing timed out") from None
        async with self.lock:
            old = next((s for s in self.store.data["subscriptions"] if s["id"] == identifier), None)
            if editing and old is None:
                raise VPNError("Subscription was deleted while downloading")
            if old:
                self.store.data["subscriptions"].remove(old)
            record = {"id": identifier, "name": name.strip(), "url": url, "nodes": nodes, "skipped": skipped, "metadata": metadata, "updated": int(time.time())}
            self.store.data["subscriptions"].append(record)
            if self.store.data["selected"] is None:
                self.store.data["selected"] = nodes[0]["id"]
            elif old and any(n["id"] == self.store.data["selected"] for n in old["nodes"]) and not any(n["id"] == self.store.data["selected"] for n in nodes):
                self.store.data["selected"] = nodes[0]["id"]
            self.store.save()
            self.state["selected"] = self.store.data["selected"]
        return {"id": identifier, "count": len(nodes), "skipped": skipped}

    async def refresh(self, identifier):
        s = self.find_subscription(identifier)
        return await self.add_or_update(s["url"], s["name"], identifier)

    async def edit(self, identifier, name, url):
        s = self.find_subscription(identifier)
        if url == "":
            url = s["url"]
        return await self.add_or_update(url, name, identifier)

    async def delete(self, identifier):
        async with self.lock:
            s = self.find_subscription(identifier)
            active = self.state["server"]
            if active and any(n["id"] == active["id"] for n in s["nodes"]) and (self.core.alive or self.state["state"] in ("CONNECTING", "CONNECTED", "DISCONNECTING")):
                raise VPNError("Disconnect before deleting the active subscription")
            self.store.data["subscriptions"].remove(s)
            if any(n["id"] == self.store.data["selected"] for n in s["nodes"]):
                self.store.data["selected"] = None
                self.state["selected"] = None
            self.store.save()
        return True

    async def select(self, identifier):
        self.find_node(identifier)
        self.store.data["selected"] = identifier
        self.state["selected"] = identifier
        self.store.save()
        return self.status()

    async def connect(self, identifier):
        async with self.lock:
            if self.closing or self.core.alive or (self.task and not self.task.done()) or self.state["state"] == "DISCONNECTING":
                raise VPNError("A VPN operation is already running")
            n = copy.deepcopy(self.find_node(identifier))
            await self.select(identifier)
            await self.set_state("CONNECTING", server=public_node(n), error=None, public_ip=None, since=None)
            self.task = asyncio.create_task(self.run_connection(n))
        return self.status()

    async def run_connection(self, n):
        try:
            await self.core.preflight()
            config = await generate(n["raw_config"])
            before = await public_ip()
            self.state["before_ip"] = before
            await self.core.start(config)
            if not await self.core.route_verified():
                raise VPNError("System traffic is not routed through the VPN interface")
            after = await public_ip()
            if not after:
                # Try alternate DNS resolver, still exclusively through VPN.
                await self.core.stop()
                config["dns"]["final"] = "dns-secondary"
                config["route"]["default_domain_resolver"] = "dns-secondary"
                await self.core.start(config)
                after = await public_ip()
            if not after or not self.core.alive or not await self.core.route_verified():
                raise VPNError("Connection timed out: tunnel traffic or DNS verification failed")
            await self.set_state("CONNECTED", public_ip=after, since=int(time.time()), error=None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error = str(e) if isinstance(e, VPNError) else "VPN core failed to start"
            try:
                await self.core.stop()
            except VPNError:
                error = "VPN cleanup failed; retry Disconnect"
            await self.set_state("ERROR", error=error, public_ip=None)

    async def disconnect(self):
        async with self.lock:
            await self.set_state("DISCONNECTING", error=None)
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            try:
                await self.core.stop()
            except VPNError as e:
                await self.set_state("ERROR", error=str(e))
                return self.status()
            await self.set_state("DISCONNECTED", server=None, error=None, public_ip=None, since=None)
            return self.status()

    async def watch(self):
        try:
            while True:
                await asyncio.sleep(2)
                if self.state["state"] == "CONNECTED" and not self.core.alive:
                    async with self.lock:
                        if self.state["state"] != "CONNECTED":
                            continue
                        try:
                            await self.core.stop()
                            message = "VPN core stopped unexpectedly; reconnect to continue"
                        except VPNError:
                            message = "VPN cleanup failed; retry Disconnect"
                        await self.set_state("ERROR", error=message, public_ip=None)
        except asyncio.CancelledError:
            return

    async def check_connection(self):
        if self.state["state"] != "CONNECTED":
            raise VPNError("Connect before verifying the tunnel")
        ip = await public_ip()
        verified = self.core.alive and await self.core.route_verified() and bool(ip)
        if self.state["state"] == "CONNECTED":
            self.state["public_ip"] = ip
        return {"verified": verified, "public_ip": ip}

    def diagnostic(self):
        # Deliberately omit server/provider labels, host, URL, keys and raw core output.
        return json.dumps({"plugin": "0.1.0", "core": CORE_VERSION, "state": self.state["state"], "core_alive": self.core.alive, "cleanup_pending": (self.runtime / "network-owned.json").exists(), "subscription_count": len(self.store.data["subscriptions"]), "platform": "SteamOS/Linux required"}, indent=2)

    def get_logs(self):
        return (self.logs / "plugin.log").read_text(encoding="utf-8")[-12000:]

    async def close(self):
        self.closing = True
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        await self.disconnect()
        self.log_handler.close()
        self.logger.removeHandler(self.log_handler)
