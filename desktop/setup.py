import json
from pathlib import Path
import subprocess

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from .jobs import submit
from .theme import button, label
from vpn.version import VERSION


BASE = Path("/var/lib/deckport-vpn")


class SetupWindow(QDialog):
    def __init__(self, root, demo=False):
        super().__init__()
        self.root = root
        self.demo = demo
        self.busy = False

        self.setWindowTitle("DeckPort VPN Setup")
        self.setMinimumSize(620, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        layout.addWidget(label("DECKPORT VPN SETUP", "eyebrow"))
        layout.addWidget(label("DeckPort VPN", "title"))
        layout.addWidget(
            label(
                f"Installed application version: {VERSION}",
                "muted",
            )
        )

        self.status = label(
            "Repair reinstalls the current verified payload without "
            "removing subscriptions or settings.",
            "muted",
        )
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        row = QHBoxLayout()

        self.repair_button = button(
            "Repair installation",
            self.repair,
            True,
        )
        self.uninstall_button = button(
            "Uninstall",
            self.uninstall,
        )

        row.addWidget(self.repair_button)
        row.addWidget(self.uninstall_button)
        layout.addLayout(row)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "Setup progress and safe installation messages appear here."
        )
        layout.addWidget(self.output, 1)

        layout.addWidget(
            label(
                "Repair and uninstall require system authorization. "
                "Closing Setup does not disconnect the VPN.",
                "muted",
            )
        )

        if demo:
            self.status.setText(
                "Design preview  system changes are disabled."
            )
            self.repair_button.setEnabled(False)
            self.uninstall_button.setEnabled(False)

    def set_busy(self, value):
        self.busy = value
        self.repair_button.setEnabled(not value and not self.demo)
        self.uninstall_button.setEnabled(not value and not self.demo)

    def current_files(self):
        current = BASE / "current"

        if not current.is_symlink():
            raise RuntimeError("DeckPort VPN installation was not found")

        release = current.resolve(strict=True)

        if release.parent != (BASE / "releases").resolve():
            raise RuntimeError("Unsafe DeckPort VPN installation")

        entry = release / "installer/entry.py"
        payload = release / "payload.zip"
        checksum = release / "payload.sha256"

        if not entry.is_file() or not payload.is_file() or not checksum.is_file():
            raise RuntimeError(
                "The installed repair payload is incomplete"
            )

        digest = checksum.read_text(
            encoding="ascii"
        ).strip()

        if len(digest) != 64 or any(
            c not in "0123456789abcdefABCDEF"
            for c in digest
        ):
            raise RuntimeError(
                "The installed payload checksum is invalid"
            )

        return entry, payload, digest.lower()

    def run_installer(self, action):
        entry, payload, digest = self.current_files()

        command = [
            "/usr/bin/pkexec",
            "/usr/bin/python3",
            "-B",
            str(entry),
            action,
        ]

        if action == "repair":
            command.extend(
                [
                    "--payload",
                    str(payload),
                    "--sha256",
                    digest,
                ]
            )

        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=240,
            check=False,
        )

        messages = []
        result = None

        for line in process.stdout.splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue

            if isinstance(item, dict):
                if "progress" in item:
                    messages.append(
                        f"{item.get('progress', 0)}%  "
                        f"{item.get('message', '')}"
                    )

                if "ok" in item:
                    result = item

        if (
            process.returncode != 0
            or not isinstance(result, dict)
            or not result.get("ok")
        ):
            raise RuntimeError(
                "Installation operation did not complete"
            )

        return {
            "messages": messages,
            "result": result,
        }

    def run_action(self, action):
        if self.busy or self.demo:
            return

        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.output.clear()
        self.status.setText(
            "Waiting for system authorization"
        )

        def success(result):
            self.set_busy(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(100)

            messages = result.get("messages", [])
            self.output.setPlainText(
                "\n".join(messages)
                or "Operation completed successfully."
            )

            self.status.setText(
                "Repair completed."
                if action == "repair"
                else "DeckPort VPN was uninstalled."
            )

        def failure(message):
            self.set_busy(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status.setText(
                "Setup could not complete the operation."
            )
            self.output.setPlainText(message)

        submit(
            lambda: self.run_installer(action),
            success,
            failure,
        )

    def repair(self):
        self.run_action("repair")

    def uninstall(self):
        answer = QMessageBox.question(
            self,
            "Uninstall DeckPort VPN",
            "Remove DeckPort VPN system components? "
            "Saved settings are kept.",
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.run_action("uninstall")
