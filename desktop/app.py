import asyncio
from pathlib import Path
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QSplitter, QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from vpn.ipc import Client
from vpn.safe_fs import read_regular
from vpn.version import VERSION
from .jobs import submit
from .theme import button, label


class DesktopWindow(QMainWindow):
    def __init__(self, root, demo=False):
        super().__init__()
        self.root, self.demo, self.client = root, demo, Client()
        self.snapshot, self.subscriptions, self.nodes, self.pings = {}, [], [], {}
        self.busy, self.polling = False, False
        self.setWindowTitle("DeckPort VPN")
        self.setWindowIcon(QIcon(str(root / "assets/deckport-vpn.svg")))
        self.resize(1060, 730)
        self.setMinimumSize(840, 600)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(label("YOUR CONNECTION. YOUR DECK.", "eyebrow"))
        header = QHBoxLayout()
        header.addWidget(label("DeckPort VPN", "title"))
        header.addStretch()
        header.addWidget(label("v" + VERSION, "muted"))
        layout.addLayout(header)
        self.status_label = label("Connecting to service…", "status")
        layout.addWidget(self.status_label)
        self.details = label("One connection across Gaming and Desktop Mode", "muted")
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.connect_button = button("Connect", self.connect_selected, True)
        self.disconnect_button = button("Disconnect", lambda: self.rpc("disconnect"))
        self.verify_button = button("Check public IP", lambda: self.rpc("check_connection"))
        for item in (self.connect_button, self.disconnect_button, self.verify_button):
            actions.addWidget(item)
        layout.addLayout(actions)
        self.error = label("")
        self.error.setStyleSheet("color: #ffb2ac")
        layout.addWidget(self.error)
        tabs = QTabWidget()
        tabs.addTab(self.servers_page(), "Servers")
        tabs.addTab(self.settings_page(), "Settings & diagnostics")
        layout.addWidget(tabs, 1)
        layout.addWidget(label("Closing this window keeps your VPN connected.", "muted"))
        self.setCentralWidget(container)
        self.make_tray()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(2000)
        if demo:
            self.load_demo()
        else:
            self.poll()

    def servers_page(self):
        page = QWidget()
        row = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(label("SUBSCRIPTIONS", "eyebrow"))
        self.sub_list = QListWidget()
        self.sub_list.setMaximumWidth(260)
        self.sub_list.currentRowChanged.connect(self.load_servers)
        left.addWidget(self.sub_list, 1)
        for title, action in (("+ Add URL", self.add_url), ("Import local file", self.import_file), ("Refresh subscription", self.refresh_subscription), ("Edit subscription", self.edit_subscription), ("Delete subscription", self.delete_subscription)):
            left.addWidget(button(title, action))
        row.addLayout(left, 1)
        right = QVBoxLayout()
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search servers")
        self.search.textChanged.connect(self.render_servers)
        filters.addWidget(self.search, 1)
        self.sort = QComboBox()
        self.sort.addItems(["Original order", "Name", "Fastest"])
        self.sort.currentIndexChanged.connect(self.render_servers)
        filters.addWidget(self.sort)
        right.addLayout(filters)
        options = QHBoxLayout()
        self.favorites = QCheckBox("Favorites only")
        self.favorites.toggled.connect(self.render_servers)
        options.addWidget(self.favorites)
        options.addStretch()
        options.addWidget(button("Ping servers", self.ping))
        right.addLayout(options)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["★", "Server", "Protocol", "Latency"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.server_clicked)
        right.addWidget(self.table, 1)
        self.sub_info = label("Add a subscription to get started.", "muted")
        right.addWidget(self.sub_info)
        row.addLayout(right, 3)
        return page

    def settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.autostart = QCheckBox("Start DeckPort VPN with Desktop Mode")
        self.autostart.clicked.connect(self.set_autostart)
        layout.addWidget(self.autostart)
        channels = QHBoxLayout()
        channels.addWidget(label("Update channel"))
        self.channel = QComboBox()
        self.channel.addItems(["Stable", "Preview"])
        self.channel.activated.connect(lambda: self.rpc("set_preferences", {"channel": self.channel.currentText().lower()}))
        channels.addWidget(self.channel)
        channels.addStretch()
        layout.addLayout(channels)
        layout.addWidget(button("Open Setup / check updates", self.open_setup))
        layout.addWidget(button("Refresh safe diagnostics", self.diagnostics))
        self.diagnostic_text = QPlainTextEdit()
        self.diagnostic_text.setReadOnly(True)
        self.diagnostic_text.setPlaceholderText("Diagnostics contain version and tunnel health, without provider addresses or credentials.")
        layout.addWidget(self.diagnostic_text, 1)
        return page

    def rpc(self, method, *args, done=None):
        if self.demo or self.busy:
            return
        self.busy = True
        self.error.setText("")
        def success(value):
            self.busy = False
            if done:
                done(value)
            self.poll()
        def failure(message):
            self.busy = False
            self.error.setText(message)
        submit(lambda: self.client.call(method, *args), success, failure)

    def poll(self):
        if self.demo or self.polling:
            return
        self.polling = True
        async def work():
            return await asyncio.gather(self.client.call("status"), self.client.call("subscriptions"), self.client.call("preferences"))
        def success(result):
            self.polling = False
            self.snapshot, subscriptions, prefs = result
            self.render_status()
            self.autostart.setChecked(prefs["autostart"])
            self.channel.setCurrentIndex(0 if prefs["channel"] == "stable" else 1)
            if subscriptions != self.subscriptions:
                previous = self.subscription_id()
                self.subscriptions = subscriptions
                self.sub_list.blockSignals(True)
                self.sub_list.clear()
                self.sub_list.addItems([f"{s['name']}\n{s['count']} servers" for s in subscriptions])
                self.sub_list.blockSignals(False)
                selected = next((i for i, s in enumerate(subscriptions) if s["id"] == previous), 0)
                self.sub_list.setCurrentRow(selected)
            elif self.subscription_id():
                self.load_servers()
        def failure(message):
            self.polling = False
            self.error.setText(message)
            self.status_label.setText("Service unavailable")
        submit(work, success, failure)

    def render_status(self):
        status = self.snapshot
        state = status.get("state", "DISCONNECTED")
        self.status_label.setText(state.replace("_", " "))
        server = status.get("server") or status.get("selected_server") or {}
        elapsed = max(0, int(time.time()) - status["since"]) if status.get("since") else 0
        self.details.setText(f"{server.get('name', 'No server selected')}  •  Public IP: {status.get('public_ip') or '—'}  •  {elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}")
        self.connect_button.setEnabled(state in ("DISCONNECTED", "ERROR") and bool(status.get("selected")) and not status.get("maintenance"))
        self.disconnect_button.setEnabled(state != "DISCONNECTED")
        self.verify_button.setEnabled(state == "CONNECTED")
        if status.get("error"):
            self.error.setText(status["error"])
        self.tray.setToolTip("DeckPort VPN · " + state)

    def subscription_id(self):
        row = self.sub_list.currentRow()
        return self.subscriptions[row]["id"] if 0 <= row < len(self.subscriptions) else None

    def load_servers(self, *_):
        identifier = self.subscription_id()
        if self.demo:
            self.render_servers()
        elif identifier:
            def done(nodes):
                if identifier == self.subscription_id():
                    self.nodes = nodes
                    self.render_servers()
            submit(lambda: self.client.call("servers", identifier), done, self.error.setText)
        else:
            self.nodes = []
            self.render_servers()
        row = self.sub_list.currentRow()
        if 0 <= row < len(self.subscriptions):
            sub = self.subscriptions[row]
            metadata = sub.get("metadata", {})
            usage = (metadata.get("upload", 0) + metadata.get("download", 0)) / 1024 ** 3
            total = metadata.get("total", 0) / 1024 ** 3
            self.sub_info.setText(f"{sub['count']} servers  •  {sub.get('skipped', 0)} entries skipped" + (f"  •  {usage:.1f} / {total:.1f} GB" if total else ""))

    def render_servers(self, *_):
        selected_id = self.table.item(self.table.currentRow(), 1)
        selected_id = selected_id.data(Qt.ItemDataRole.UserRole) if selected_id else self.snapshot.get("selected")
        nodes = [n for n in self.nodes if self.search.text().casefold() in n["name"].casefold() and (not self.favorites.isChecked() or n.get("favorite"))]
        if self.sort.currentIndex() == 1:
            nodes.sort(key=lambda n: n["name"].casefold())
        elif self.sort.currentIndex() == 2:
            nodes.sort(key=lambda n: self.pings.get(n["id"], {}).get("latency_ms") or 1000000)
        self.table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            ping = self.pings.get(node["id"], {})
            latency = f"{ping['latency_ms']} ms" if ping.get("latency_ms") else ping.get("status", "—")
            for column, value in enumerate(("★" if node.get("favorite") else "☆", node["name"], node["protocol"].upper(), latency)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, node["id"])
                self.table.setItem(row, column, item)
            if node["id"] == selected_id:
                self.table.selectRow(row)

    def server_clicked(self, row, column):
        identifier = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        if column == 0:
            favorite = next(n.get("favorite", False) for n in self.nodes if n["id"] == identifier)
            self.rpc("favorite", identifier, not favorite, done=lambda _: self.load_servers())
        else:
            self.rpc("select", identifier)

    def connect_selected(self):
        identifier = self.snapshot.get("selected")
        if identifier:
            self.rpc("connect", identifier)

    def ping(self):
        if self.subscription_id():
            def done(results):
                self.pings = {item["id"]: item for item in results}
                self.render_servers()
            self.rpc("ping_servers", self.subscription_id(), done=done)

    def add_url(self):
        self.subscription_dialog()

    def subscription_dialog(self, editing=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit subscription" if editing else "Add subscription")
        dialog.setMinimumWidth(480)
        form = QFormLayout(dialog)
        name, url = QLineEdit(), QLineEdit()
        name.setMaxLength(80)
        url.setMaxLength(8192)
        url.setEchoMode(QLineEdit.EchoMode.Password)
        name.setText(editing["name"] if editing else "My subscription")
        url.setPlaceholderText("Leave empty to keep the saved URL" if editing else "https://provider.example/subscription")
        form.addRow("Name", name)
        form.addRow("Provider URL", url)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = (editing["id"], name.text(), url.text()) if editing else (url.text(), name.text())
            self.rpc("edit" if editing else "add_or_update", *values)
        url.clear()
        dialog.deleteLater()

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import subscription", str(Path.home()), "Subscriptions (*.txt *.conf *.json *.yaml *.yml)")
        if not filename:
            return
        name, accepted = QInputDialog.getText(self, "Import subscription", "Subscription name", text=Path(filename).stem[:80])
        if accepted:
            try:
                content = read_regular(Path(filename), 4 * 1024 * 1024).decode("utf-8-sig")
                self.rpc("import_content", content, name)
            except Exception:
                self.error.setText("Choose a regular UTF-8 subscription file under 4 MiB.")

    def refresh_subscription(self):
        if self.subscription_id():
            self.rpc("refresh", self.subscription_id())

    def edit_subscription(self):
        row = self.sub_list.currentRow()
        if row >= 0:
            sub = self.subscriptions[row]
            if sub["source_type"] == "url":
                self.subscription_dialog(sub)
            else:
                self.error.setText("Import the updated local file to replace its contents.")

    def delete_subscription(self):
        identifier = self.subscription_id()
        if identifier and QMessageBox.question(self, "Delete subscription", "Remove this subscription and its servers?") == QMessageBox.StandardButton.Yes:
            self.rpc("delete", identifier)

    def diagnostics(self):
        async def work():
            parts = await asyncio.gather(self.client.call("diagnostic"), self.client.call("get_logs"))
            return "\n\n".join(parts)
        submit(work, self.diagnostic_text.setPlainText, self.error.setText)

    def set_autostart(self, enabled):
        from installer.transaction import launcher_text, BASE
        from installer.user_files import directory, write_at
        path = Path.home() / ".config/autostart"
        try:
            if enabled:
                with directory(path, create=True) as fd:
                    write_at(fd, "deckport-vpn.desktop", launcher_text(BASE).replace("[Desktop Entry]", "[Desktop Entry]\nOnlyShowIn=KDE;\nX-KDE-autostart-after=panel").encode())
            else:
                (path / "deckport-vpn.desktop").unlink(missing_ok=True)
            self.rpc("set_preferences", {"autostart": enabled})
        except Exception:
            self.error.setText("The Desktop startup preference could not be saved.")

    def make_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        for title, action in (("Open DeckPort VPN", self.show_window), ("Connect", self.connect_selected), ("Disconnect", lambda: self.rpc("disconnect")), ("Quit application (keep VPN)", QApplication.instance().quit)):
            entry = QAction(title, menu)
            entry.triggered.connect(action)
            menu.addAction(entry)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def open_setup(self):
        from .setup import SetupWindow
        self.setup_window = SetupWindow(self.root, demo=self.demo)
        self.setup_window.show()

    def closeEvent(self, event):
        if self.tray.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def load_demo(self):
        self.subscriptions = [{"id": "demo", "name": "My subscription", "count": 6, "source_type": "url", "skipped": 0}]
        self.nodes = [{"id": str(i), "name": name, "protocol": protocol, "favorite": i < 2} for i, (name, protocol) in enumerate([("Netherlands · Amsterdam", "vless"), ("Germany · Frankfurt", "trojan"), ("Finland · Helsinki", "wireguard"), ("Sweden · Stockholm", "vless"), ("France · Paris", "shadowsocks"), ("United Kingdom · London", "vmess")])]
        self.pings = {str(i): {"latency_ms": value} for i, value in enumerate([24, 31, None, 43, 49, 56])}
        self.snapshot = {"state": "CONNECTED", "server": self.nodes[0], "selected": "0", "public_ip": "203.0.113.24", "since": int(time.time()) - 754}
        self.sub_list.addItem("My subscription\n6 servers")
        self.sub_list.setCurrentRow(0)
        self.render_status()
        self.render_servers()
        self.error.setText("Design preview · sample data · no VPN connection")
