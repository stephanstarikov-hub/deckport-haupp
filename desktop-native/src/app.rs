use crate::{ipc, setup};
use eframe::egui;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    process::Command,
    sync::mpsc::{self, Receiver, Sender},
    thread,
    time::{Duration, Instant},
};

const VERSION: &str = env!("DECKPORT_VERSION");

#[derive(Clone, Copy, PartialEq, Eq)]
enum Page {
    Vpn,
    Servers,
    Subscriptions,
    Settings,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum SortMode {
    Default,
    Latency,
    Name,
}

enum WorkerMessage {
    Snapshot(Result<(Value, Vec<Value>, Value), String>),
    Servers {
        subscription: String,
        result: Result<Vec<Value>, String>,
    },
    Pings {
        subscription: String,
        result: Result<Vec<Value>, String>,
    },
    Mutation {
        method: &'static str,
        result: Result<Value, String>,
        success: String,
        reload_servers: bool,
    },
    Diagnostics(Result<String, String>),
}

pub struct DeckPortApp {
    page: Page,
    status: Value,
    subscriptions: Vec<Value>,
    servers: Vec<Value>,
    selected_subscription: Option<String>,

    search: String,
    sort_mode: SortMode,
    favorites_only: bool,
    pings: HashMap<String, (String, Option<u64>)>,
    preferences: Value,
    diagnostics: String,

    error: String,
    notice: String,

    last_refresh: Instant,
    refresh_busy: bool,
    ping_busy: bool,
    action_busy: bool,
    diagnostics_busy: bool,
    loading_subscription: Option<String>,

    tx: Sender<WorkerMessage>,
    rx: Receiver<WorkerMessage>,

    add_mode: bool,
    add_name: String,
    add_url: String,

    edit_mode: bool,
    edit_name: String,
    edit_url: String,
    confirm_delete: bool,

    import_mode: bool,
    import_name: String,
    import_content: String,

    setup: Option<setup::SetupState>,
}

impl DeckPortApp {
    pub fn new() -> Self {
        let (tx, rx) = mpsc::channel();

        let mut app = Self {
            page: Page::Vpn,
            status: json!({}),
            subscriptions: Vec::new(),
            servers: Vec::new(),
            selected_subscription: None,

            search: String::new(),
            sort_mode: SortMode::Default,
            favorites_only: false,
            pings: HashMap::new(),
            preferences: json!({
                "channel": "stable",
                "autostart": false,
            }),
            diagnostics: String::new(),

            error: String::new(),
            notice: String::new(),

            last_refresh: Instant::now() - Duration::from_secs(10),
            refresh_busy: false,
            ping_busy: false,
            action_busy: false,
            diagnostics_busy: false,
            loading_subscription: None,

            tx,
            rx,

            add_mode: false,
            add_name: String::new(),
            add_url: String::new(),

            edit_mode: false,
            edit_name: String::new(),
            edit_url: String::new(),
            confirm_delete: false,

            import_mode: false,
            import_name: String::new(),
            import_content: String::new(),

            setup: None,
        };

        app.request_refresh();
        app
    }

    pub fn new_setup() -> Self {
        let (tx, rx) = mpsc::channel();

        Self {
            page: Page::Vpn,
            status: json!({}),
            subscriptions: Vec::new(),
            servers: Vec::new(),
            selected_subscription: None,

            search: String::new(),
            sort_mode: SortMode::Default,
            favorites_only: false,
            pings: HashMap::new(),
            preferences: json!({
                "channel": "stable",
                "autostart": false,
            }),
            diagnostics: String::new(),

            error: String::new(),
            notice: String::new(),

            last_refresh: Instant::now(),
            refresh_busy: false,
            ping_busy: false,
            action_busy: false,
            diagnostics_busy: false,
            loading_subscription: None,

            tx,
            rx,

            add_mode: false,
            add_name: String::new(),
            add_url: String::new(),

            edit_mode: false,
            edit_name: String::new(),
            edit_url: String::new(),
            confirm_delete: false,

            import_mode: false,
            import_name: String::new(),
            import_content: String::new(),

            setup: Some(setup::SetupState::new()),
        }
    }

    fn request_refresh(&mut self) {
        if self.refresh_busy || self.setup.is_some() {
            return;
        }

        self.refresh_busy = true;

        let tx = self.tx.clone();

        thread::spawn(move || {
            let result = (|| -> Result<(Value, Vec<Value>, Value), String> {
                let status = ipc::call("status", vec![])?;

                let subscriptions = ipc::call("subscriptions", vec![])?
                    .as_array()
                    .cloned()
                    .ok_or_else(|| "Invalid subscriptions response".to_string())?;

                let preferences = ipc::call("preferences", vec![])?;

                Ok((status, subscriptions, preferences))
            })();

            let _ = tx.send(WorkerMessage::Snapshot(result));
        });
    }

    fn request_servers(&mut self) {
        let Some(subscription) = self.selected_subscription.clone() else {
            self.servers.clear();
            self.loading_subscription = None;
            return;
        };

        if self.loading_subscription.as_deref() == Some(subscription.as_str()) {
            return;
        }

        self.loading_subscription = Some(subscription.clone());

        let tx = self.tx.clone();

        thread::spawn(move || {
            let result =
                ipc::call("servers", vec![json!(subscription.clone())]).and_then(|value| {
                    value
                        .as_array()
                        .cloned()
                        .ok_or_else(|| "Invalid servers response".to_string())
                });

            let _ = tx.send(WorkerMessage::Servers {
                subscription,
                result,
            });
        });
    }

    fn request_ping(&mut self) {
        if self.ping_busy {
            return;
        }

        let Some(subscription) = self.selected_subscription.clone() else {
            return;
        };

        self.ping_busy = true;
        self.error.clear();

        let tx = self.tx.clone();

        thread::spawn(move || {
            let result =
                ipc::call("ping_servers", vec![json!(subscription.clone())]).and_then(|value| {
                    value
                        .as_array()
                        .cloned()
                        .ok_or_else(|| "Invalid ping response".to_string())
                });

            let _ = tx.send(WorkerMessage::Pings {
                subscription,
                result,
            });
        });
    }

    fn request_mutation(
        &mut self,
        method: &'static str,
        args: Vec<Value>,
        success: impl Into<String>,
        reload_servers: bool,
    ) {
        if self.action_busy {
            return;
        }

        self.action_busy = true;
        self.error.clear();
        self.notice.clear();

        let tx = self.tx.clone();
        let success = success.into();

        thread::spawn(move || {
            let result = ipc::call(method, args);

            let _ = tx.send(WorkerMessage::Mutation {
                method,
                result,
                success,
                reload_servers,
            });
        });
    }

    fn request_diagnostics(&mut self) {
        if self.diagnostics_busy {
            return;
        }

        self.diagnostics_busy = true;
        self.error.clear();

        let tx = self.tx.clone();

        thread::spawn(move || {
            let result = (|| -> Result<String, String> {
                let diagnostic = ipc::call("diagnostic", vec![])?
                    .as_str()
                    .ok_or_else(|| "Invalid diagnostic response".to_string())?
                    .to_string();

                let logs = ipc::call("get_logs", vec![])?
                    .as_str()
                    .ok_or_else(|| "Invalid log response".to_string())?
                    .to_string();

                Ok(format!("{diagnostic}\n\n{logs}"))
            })();

            let _ = tx.send(WorkerMessage::Diagnostics(result));
        });
    }

    fn request_file_import(&mut self) {
        if self.action_busy {
            return;
        }

        self.action_busy = true;
        self.error.clear();
        self.notice.clear();

        let tx = self.tx.clone();

        thread::spawn(move || {
            let result = import_local_file();

            let success = if result.as_ref().ok().and_then(|value| value.as_bool()) == Some(false) {
                "Import cancelled".to_string()
            } else {
                "Local subscription imported".to_string()
            };

            let _ = tx.send(WorkerMessage::Mutation {
                method: "import_content",
                result,
                success,
                reload_servers: true,
            });
        });
    }

    fn subscription_exists(&self, id: &str) -> bool {
        self.subscriptions
            .iter()
            .any(|item| item.get("id").and_then(Value::as_str) == Some(id))
    }

    fn selected_subscription_value(&self) -> Option<&Value> {
        let id = self.selected_subscription.as_deref()?;

        self.subscriptions
            .iter()
            .find(|item| item.get("id").and_then(Value::as_str) == Some(id))
    }

    fn choose_subscription(&mut self, id: String) {
        if self.selected_subscription.as_deref() == Some(id.as_str()) {
            return;
        }

        self.selected_subscription = Some(id);

        self.pings.clear();
        self.search.clear();
        self.sort_mode = SortMode::Default;

        self.edit_mode = false;
        self.confirm_delete = false;

        self.sync_edit_name();
        self.request_servers();
    }

    fn sync_edit_name(&mut self) {
        self.edit_name = self
            .selected_subscription_value()
            .and_then(|item| item.get("name"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();

        self.edit_url.clear();
    }

    fn state(&self) -> &str {
        self.status
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("UNKNOWN")
    }

    fn selected_server_id(&self) -> Option<&str> {
        self.status.get("selected").and_then(Value::as_str)
    }

    fn ping_label(&self, id: &str) -> String {
        match self.pings.get(id) {
            Some((status, Some(ms))) if status == "ok" => {
                format!("{ms} ms")
            }

            Some((status, _)) if status == "unsupported" => "unsupported".to_string(),

            Some((status, _)) if status == "blocked" => "blocked".to_string(),

            Some(_) => "timeout".to_string(),

            None => "-".to_string(),
        }
    }

    fn latency(&self, id: &str) -> u64 {
        self.pings
            .get(id)
            .and_then(
                |(status, latency)| {
                    if status == "ok" { *latency } else { None }
                },
            )
            .unwrap_or(u64::MAX)
    }
    fn process_messages(&mut self) {
        let mut reload_servers = false;
        let mut refresh_after = false;

        while let Ok(message) = self.rx.try_recv() {
            match message {
                WorkerMessage::Snapshot(result) => {
                    self.refresh_busy = false;
                    self.last_refresh = Instant::now();

                    match result {
                        Ok((status, subscriptions, preferences)) => {
                            let subscriptions_changed = self.subscriptions != subscriptions;
                            let preferred = status
                                .get("selected_subscription")
                                .and_then(Value::as_str)
                                .map(str::to_owned);

                            self.status = status;
                            self.subscriptions = subscriptions;
                            self.preferences = preferences;
                            self.error.clear();

                            let keep_current = self
                                .selected_subscription
                                .as_ref()
                                .filter(|id| self.subscription_exists(id))
                                .cloned();

                            let preferred = preferred.filter(|id| self.subscription_exists(id));

                            let next = keep_current.or(preferred).or_else(|| {
                                self.subscriptions
                                    .first()
                                    .and_then(|item| item.get("id").and_then(Value::as_str))
                                    .map(str::to_owned)
                            });

                            if self.selected_subscription != next {
                                self.selected_subscription = next;
                                self.pings.clear();
                                self.sort_mode = SortMode::Default;
                                self.sync_edit_name();
                                reload_servers = true;
                            } else if self.servers.is_empty()
                                && self.selected_subscription.is_some()
                            {
                                reload_servers = true;
                            } else if subscriptions_changed && self.selected_subscription.is_some()
                            {
                                // Decky and Desktop share daemon storage. Reload
                                // the active server list when either client has
                                // refreshed, edited, or replaced a subscription.
                                reload_servers = true;
                            }
                        }

                        Err(message) => {
                            self.error = message;
                        }
                    }
                }

                WorkerMessage::Servers {
                    subscription,
                    result,
                } => {
                    if self.loading_subscription.as_deref() == Some(subscription.as_str()) {
                        self.loading_subscription = None;
                    }

                    if self.selected_subscription.as_deref() != Some(subscription.as_str()) {
                        continue;
                    }

                    match result {
                        Ok(servers) => {
                            self.servers = servers;
                            self.error.clear();
                        }

                        Err(message) => {
                            self.error = message;
                        }
                    }
                }

                WorkerMessage::Pings {
                    subscription,
                    result,
                } => {
                    self.ping_busy = false;

                    if self.selected_subscription.as_deref() != Some(subscription.as_str()) {
                        continue;
                    }

                    match result {
                        Ok(items) => {
                            self.pings.clear();

                            for item in items {
                                let Some(id) = item.get("id").and_then(Value::as_str) else {
                                    continue;
                                };

                                let status = item
                                    .get("status")
                                    .and_then(Value::as_str)
                                    .unwrap_or("timeout")
                                    .to_string();

                                let latency = item.get("latency_ms").and_then(Value::as_u64);

                                self.pings.insert(id.to_string(), (status, latency));
                            }

                            self.sort_mode = SortMode::Latency;
                            self.notice = "Ping check completed".to_string();
                            self.error.clear();
                        }

                        Err(message) => {
                            self.error = message;
                        }
                    }
                }

                WorkerMessage::Mutation {
                    method,
                    result,
                    success,
                    reload_servers: reload,
                } => {
                    self.action_busy = false;

                    match result {
                        Ok(_) => {
                            self.notice = success;
                            self.error.clear();
                            refresh_after = true;

                            match method {
                                "add_or_update" => {
                                    self.add_mode = false;
                                    self.add_name.clear();
                                    self.add_url.clear();
                                }
                                "import_content" => {
                                    self.import_mode = false;
                                    self.import_name.clear();
                                    self.import_content.clear();
                                }
                                "edit" => {
                                    self.edit_mode = false;
                                    self.edit_url.clear();
                                }
                                "delete" => self.confirm_delete = false,
                                _ => {}
                            }

                            if reload {
                                reload_servers = true;
                            }
                        }

                        Err(message) => {
                            self.error = message;
                        }
                    }
                }

                WorkerMessage::Diagnostics(result) => {
                    self.diagnostics_busy = false;

                    match result {
                        Ok(content) => {
                            self.diagnostics = content;
                            self.error.clear();
                        }
                        Err(message) => {
                            self.error = message;
                        }
                    }
                }
            }
        }

        if refresh_after {
            self.request_refresh();
        }

        if reload_servers {
            self.request_servers();
        }
    }

    fn ui_header(&mut self, ui: &mut egui::Ui) {
        let green = egui::Color32::from_rgb(61, 240, 149);
        let muted = egui::Color32::from_rgb(143, 163, 183);
        let active = egui::Color32::from_rgb(16, 40, 58);

        ui.set_width(205.0);
        ui.set_min_height(ui.available_height());
        ui.add_space(10.0);

        ui.horizontal(|ui| {
            ui.label(egui::RichText::new("◆").size(28.0).strong().color(green));
            ui.vertical(|ui| {
                ui.label(egui::RichText::new("DeckPort").size(22.0).strong());
                ui.label(
                    egui::RichText::new("Your Privacy. Your Way.")
                        .size(11.0)
                        .color(muted),
                );
            });
        });

        ui.add_space(34.0);

        for (page, icon, label) in [
            (Page::Vpn, "⌂", "Home"),
            (Page::Servers, "◉", "Servers"),
            (Page::Subscriptions, "↗", "Subscriptions"),
            (Page::Settings, "⚙", "Settings"),
        ] {
            let selected = self.page == page;
            let button = egui::Button::new(
                egui::RichText::new(format!("{icon}   {label}"))
                    .size(15.0)
                    .color(if selected {
                        egui::Color32::WHITE
                    } else {
                        muted
                    }),
            )
            .fill(if selected {
                active
            } else {
                egui::Color32::TRANSPARENT
            })
            .stroke(egui::Stroke::new(
                1.0,
                if selected {
                    egui::Color32::from_rgb(27, 65, 84)
                } else {
                    egui::Color32::TRANSPARENT
                },
            ))
            .min_size(egui::vec2(185.0, 44.0));

            if ui.add(button).clicked() {
                self.page = page;
            }
            ui.add_space(3.0);
        }

        ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
            ui.add_space(10.0);
            ui.label(
                egui::RichText::new(format!("v{VERSION}"))
                    .size(11.0)
                    .color(egui::Color32::from_rgb(96, 118, 140)),
            );
            ui.label(
                egui::RichText::new("●  Connected to core")
                    .size(11.0)
                    .color(green),
            );
        });
    }

    fn ui_feedback(&mut self, ui: &mut egui::Ui) {
        if !self.error.is_empty() {
            ui.colored_label(egui::Color32::from_rgb(255, 126, 144), &self.error);
            ui.add_space(6.0);
        }
        if !self.notice.is_empty() {
            ui.colored_label(egui::Color32::from_rgb(100, 240, 167), &self.notice);
            ui.add_space(6.0);
        }
    }

    fn ui_vpn(&mut self, ui: &mut egui::Ui) {
        let green = egui::Color32::from_rgb(61, 240, 149);
        let muted = egui::Color32::from_rgb(143, 163, 183);
        let panel = egui::Color32::from_rgb(11, 27, 39);
        let border = egui::Color32::from_rgb(23, 52, 72);

        let state = self.state().to_string();
        let connected = state == "CONNECTED";
        let selected = self
            .status
            .get("server")
            .filter(|value| !value.is_null())
            .or_else(|| self.status.get("selected_server"))
            .cloned()
            .unwrap_or(Value::Null);

        let name = selected
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("Choose a server")
            .to_string();
        let protocol = selected
            .get("protocol")
            .and_then(Value::as_str)
            .unwrap_or("—")
            .to_uppercase();
        let public_ip = self
            .status
            .get("public_ip")
            .and_then(Value::as_str)
            .unwrap_or("—")
            .to_string();

        ui.heading(egui::RichText::new("VPN").size(26.0).strong());
        ui.label(egui::RichText::new("One tap to secure your Steam Deck connection.").color(muted));
        ui.add_space(16.0);

        ui.columns(2, |columns| {
            columns[0].vertical_centered(|ui| {
                ui.label(
                    egui::RichText::new(if connected {
                        "🔒  Secure Connection"
                    } else {
                        "Connection ready"
                    })
                    .color(if connected { green } else { muted }),
                );
                ui.add_space(16.0);

                let (rect, response) =
                    ui.allocate_exact_size(egui::vec2(190.0, 190.0), egui::Sense::click());
                let center = rect.center();
                let ring = if connected {
                    green
                } else {
                    egui::Color32::from_rgb(77, 101, 119)
                };

                ui.painter()
                    .circle_filled(center, 84.0, egui::Color32::from_rgb(8, 27, 24));
                ui.painter()
                    .circle_stroke(center, 86.0, egui::Stroke::new(2.0, ring));
                ui.painter().text(
                    center,
                    egui::Align2::CENTER_CENTER,
                    "⏻",
                    egui::FontId::proportional(56.0),
                    ring,
                );

                if response.clicked() && !self.action_busy {
                    if connected
                        || matches!(
                            state.as_str(),
                            "CONNECTING" | "RECONNECTING" | "DISCONNECTING" | "ERROR"
                        )
                    {
                        self.request_mutation("disconnect", vec![], "VPN disconnected", false);
                    } else if let Some(id) = self.selected_server_id().map(str::to_owned) {
                        self.request_mutation(
                            "connect",
                            vec![json!(id)],
                            "Connection started",
                            false,
                        );
                    } else {
                        self.page = Page::Servers;
                    }
                }

                ui.add_space(12.0);
                ui.label(
                    egui::RichText::new(if connected {
                        "Connected"
                    } else {
                        "Disconnected"
                    })
                    .size(23.0)
                    .strong()
                    .color(if connected { green } else { muted }),
                );

                if let Some(since) = self.status.get("since").and_then(Value::as_i64) {
                    ui.label(
                        egui::RichText::new(elapsed_label(since))
                            .size(13.0)
                            .color(muted),
                    );
                }

                ui.add_space(12.0);
                if ui
                    .add(
                        egui::Button::new(format!("◉  {name}     ›"))
                            .fill(egui::Color32::from_rgb(14, 32, 45))
                            .stroke(egui::Stroke::new(1.0, border))
                            .min_size(egui::vec2(310.0, 50.0)),
                    )
                    .clicked()
                {
                    self.page = Page::Servers;
                }
            });

            let right = &mut columns[1];
            egui::Frame::group(right.style())
                .fill(panel)
                .stroke(egui::Stroke::new(1.0, border))
                .show(right, |ui| {
                    ui.label(egui::RichText::new("Connection").size(17.0).strong());
                    ui.add_space(8.0);
                    for (key, value) in [
                        ("State", state.replace('_', " ")),
                        ("Protocol", protocol),
                        ("Server", name.clone()),
                        ("Public IP", public_ip),
                    ] {
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new(key).color(muted));
                            ui.with_layout(
                                egui::Layout::right_to_left(egui::Align::Center),
                                |ui| {
                                    ui.label(egui::RichText::new(value).strong());
                                },
                            );
                        });
                        ui.add_space(5.0);
                    }
                });

            right.add_space(12.0);
            egui::Frame::group(right.style())
                .fill(panel)
                .stroke(egui::Stroke::new(1.0, border))
                .show(right, |ui| {
                    ui.label(egui::RichText::new("Quick Actions").size(17.0).strong());
                    ui.add_space(8.0);

                    if ui
                        .add(
                            egui::Button::new("◉  Change Server")
                                .min_size(egui::vec2(ui.available_width(), 38.0)),
                        )
                        .clicked()
                    {
                        self.page = Page::Servers;
                    }

                    if ui
                        .add_enabled(
                            !self.refresh_busy,
                            egui::Button::new(if self.refresh_busy {
                                "Refreshing…"
                            } else {
                                "↻  Refresh status"
                            })
                            .min_size(egui::vec2(ui.available_width(), 38.0)),
                        )
                        .clicked()
                    {
                        self.request_refresh();
                    }
                });

            right.add_space(12.0);
            egui::Frame::group(right.style())
                .fill(if connected {
                    egui::Color32::from_rgb(9, 38, 29)
                } else {
                    panel
                })
                .stroke(egui::Stroke::new(
                    1.0,
                    if connected { green } else { border },
                ))
                .show(right, |ui| {
                    ui.label(
                        egui::RichText::new(if connected {
                            "◆  Your connection is secure"
                        } else {
                            "◇  VPN is disconnected"
                        })
                        .strong()
                        .color(if connected { green } else { muted }),
                    );
                    ui.label(
                        egui::RichText::new(if connected {
                            "Traffic is protected through the active VPN tunnel."
                        } else {
                            "Choose a server and press the power button."
                        })
                        .size(12.0)
                        .color(muted),
                    );
                });
        });
    }

    fn ui_servers(&mut self, ui: &mut egui::Ui) {
        ui.heading("Servers");

        let options: Vec<(String, String)> = self
            .subscriptions
            .iter()
            .filter_map(|item| {
                Some((
                    item.get("id")?.as_str()?.to_string(),
                    item.get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("Subscription")
                        .to_string(),
                ))
            })
            .collect();

        if options.is_empty() {
            ui.label("No subscriptions. Add one on the Subscriptions page.");

            if ui.button("Add subscription").clicked() {
                self.page = Page::Subscriptions;
                self.add_mode = true;
            }

            return;
        }

        let current_name = options
            .iter()
            .find(|(id, _)| self.selected_subscription.as_deref() == Some(id.as_str()))
            .map(|(_, name)| name.as_str())
            .unwrap_or("Choose subscription");

        let mut change_subscription = None;

        ui.horizontal(|ui| {
            egui::ComboBox::from_id_salt("desktop_subscription_selector")
                .selected_text(current_name)
                .show_ui(ui, |ui| {
                    for (id, name) in &options {
                        let selected = self.selected_subscription.as_deref() == Some(id.as_str());

                        if ui.selectable_label(selected, name).clicked() {
                            change_subscription = Some(id.clone());
                        }
                    }
                });

            if ui
                .add_enabled(
                    !self.ping_busy && self.selected_subscription.is_some(),
                    egui::Button::new(if self.ping_busy {
                        "Pinging..."
                    } else {
                        "Ping All"
                    }),
                )
                .clicked()
            {
                self.request_ping();
            }

            if self.loading_subscription.is_some() {
                ui.spinner();
            }
        });

        if let Some(id) = change_subscription {
            self.choose_subscription(id);
        }

        ui.add_space(8.0);

        ui.horizontal(|ui| {
            ui.add(egui::TextEdit::singleline(&mut self.search).hint_text("Search servers"));

            ui.label("Sort:");

            ui.selectable_value(&mut self.sort_mode, SortMode::Default, "Default");

            ui.selectable_value(&mut self.sort_mode, SortMode::Latency, "Ping");

            ui.selectable_value(&mut self.sort_mode, SortMode::Name, "Name");

            ui.separator();
            ui.checkbox(&mut self.favorites_only, "Favorites only");
        });

        ui.separator();

        let query = self.search.to_lowercase();

        let mut servers: Vec<Value> = self
            .servers
            .iter()
            .filter(|server| {
                let name = server.get("name").and_then(Value::as_str).unwrap_or("");

                let protocol = server.get("protocol").and_then(Value::as_str).unwrap_or("");
                let country = server.get("country").and_then(Value::as_str).unwrap_or("");
                let matches_search = query.is_empty()
                    || name.to_lowercase().contains(&query)
                    || protocol.to_lowercase().contains(&query)
                    || country.to_lowercase().contains(&query);

                let favorite = server
                    .get("favorite")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);

                matches_search && (!self.favorites_only || favorite)
            })
            .cloned()
            .collect();

        match self.sort_mode {
            SortMode::Default => {}

            SortMode::Latency => {
                servers.sort_by_key(|server| {
                    server
                        .get("id")
                        .and_then(Value::as_str)
                        .map(|id| self.latency(id))
                        .unwrap_or(u64::MAX)
                });
            }

            SortMode::Name => {
                servers.sort_by(|a, b| {
                    let a = a
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_lowercase();

                    let b = b
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_lowercase();

                    a.cmp(&b)
                });
            }
        }

        let mut select_server = None;
        let mut favorite_change = None;

        egui::ScrollArea::vertical().show(ui, |ui| {
            for server in servers {
                let Some(id) = server.get("id").and_then(Value::as_str).map(str::to_owned) else {
                    continue;
                };

                let name = server
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("Unnamed server");

                let protocol = server
                    .get("protocol")
                    .and_then(Value::as_str)
                    .unwrap_or("?")
                    .to_uppercase();

                let country = server.get("country").and_then(Value::as_str).unwrap_or("");

                let favorite = server
                    .get("favorite")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);

                let selected = self.selected_server_id() == Some(id.as_str());

                let ping = self.ping_label(&id);

                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(
                            !self.action_busy,
                            egui::Button::new(if favorite { "\u{2605}" } else { "\u{2606}" }),
                        )
                        .clicked()
                    {
                        favorite_change = Some((id.clone(), !favorite));
                    }

                    if ui.selectable_label(selected, name).clicked() {
                        select_server = Some(id.clone());
                    }

                    ui.label(protocol);

                    if !country.is_empty() {
                        ui.label(country);
                    }

                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(ping);
                    });
                });

                ui.separator();
            }
        });

        if let Some((id, enabled)) = favorite_change {
            self.request_mutation(
                "favorite",
                vec![json!(id), json!(enabled)],
                if enabled {
                    "Added to favorites"
                } else {
                    "Removed from favorites"
                },
                true,
            );
        }

        if let Some(id) = select_server {
            self.request_mutation("select", vec![json!(id)], "Server selected", false);
        }
    }

    fn ui_subscriptions(&mut self, ui: &mut egui::Ui) {
        ui.heading("Subscriptions");
        ui.label("Decky and Desktop use this same list through deckportd.");
        ui.add_space(8.0);

        ui.horizontal(|ui| {
            if ui
                .add_enabled(!self.action_busy, egui::Button::new("Add subscription"))
                .clicked()
            {
                self.add_mode = !self.add_mode;
                self.import_mode = false;
                self.confirm_delete = false;
            }

            if ui
                .add_enabled(!self.action_busy, egui::Button::new("Import local file"))
                .clicked()
            {
                self.request_file_import();
            }

            if ui
                .add_enabled(!self.action_busy, egui::Button::new("Import pasted text"))
                .clicked()
            {
                self.import_mode = !self.import_mode;
                self.add_mode = false;
                self.confirm_delete = false;
            }
        });

        if self.add_mode {
            ui.add_space(8.0);
            ui.group(|ui| {
                ui.strong("Add subscription URL");
                ui.label("Name");
                ui.add(
                    egui::TextEdit::singleline(&mut self.add_name)
                        .char_limit(80)
                        .hint_text("My subscription"),
                );
                ui.label("Provider URL");
                ui.add(
                    egui::TextEdit::singleline(&mut self.add_url)
                        .password(true)
                        .char_limit(8192)
                        .hint_text("https://provider.example/subscription"),
                );

                ui.horizontal(|ui| {
                    let valid = !self.add_name.trim().is_empty()
                        && !self.add_url.trim().is_empty()
                        && !self.action_busy;

                    if ui.add_enabled(valid, egui::Button::new("Add")).clicked() {
                        let name = self.add_name.trim().to_string();
                        let url = self.add_url.trim().to_string();

                        self.request_mutation(
                            "add_or_update",
                            vec![json!(url), json!(name)],
                            "Subscription added",
                            true,
                        );
                    }

                    if ui.button("Cancel").clicked() {
                        self.add_mode = false;
                        self.add_url.clear();
                    }
                });
            });
        }

        if self.import_mode {
            ui.add_space(8.0);
            ui.group(|ui| {
                ui.strong("Import subscription text");
                ui.label("Name");
                ui.add(
                    egui::TextEdit::singleline(&mut self.import_name)
                        .char_limit(80)
                        .hint_text("Imported subscription"),
                );
                ui.label("Paste URI lines, Base64, Clash, sing-box JSON, or WireGuard config.");
                ui.add_sized(
                    [ui.available_width(), 140.0],
                    egui::TextEdit::multiline(&mut self.import_content)
                        .password(true)
                        .char_limit(4 * 1024 * 1024),
                );

                ui.horizontal(|ui| {
                    let valid = !self.import_name.trim().is_empty()
                        && !self.import_content.trim().is_empty()
                        && !self.action_busy;

                    if ui.add_enabled(valid, egui::Button::new("Import")).clicked() {
                        let name = self.import_name.trim().to_string();
                        let content = self.import_content.clone();

                        self.request_mutation(
                            "import_content",
                            vec![json!(content), json!(name)],
                            "Subscription imported",
                            true,
                        );
                    }

                    if ui.button("Cancel").clicked() {
                        self.import_mode = false;
                        self.import_content.clear();
                    }
                });
            });
        }

        ui.separator();

        let subscriptions: Vec<(String, String, u64, String)> = self
            .subscriptions
            .iter()
            .filter_map(|item| {
                Some((
                    item.get("id")?.as_str()?.to_string(),
                    item.get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("Subscription")
                        .to_string(),
                    item.get("count").and_then(Value::as_u64).unwrap_or(0),
                    item.get("source_type")
                        .and_then(Value::as_str)
                        .unwrap_or("url")
                        .to_string(),
                ))
            })
            .collect();

        let mut choose = None;

        egui::ScrollArea::vertical()
            .max_height(190.0)
            .show(ui, |ui| {
                for (id, name, count, source) in &subscriptions {
                    let selected = self.selected_subscription.as_deref() == Some(id.as_str());

                    if ui
                        .selectable_label(
                            selected,
                            format!("{name}  -  {count} servers  -  {source}"),
                        )
                        .clicked()
                    {
                        choose = Some(id.clone());
                    }
                }
            });

        if let Some(id) = choose {
            self.choose_subscription(id);
        }

        let selected = self.selected_subscription_value().cloned();

        let Some(subscription) = selected else {
            ui.add_space(8.0);
            ui.label("No subscriptions yet.");
            return;
        };

        let id = subscription
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let source_type = subscription
            .get("source_type")
            .and_then(Value::as_str)
            .unwrap_or("url");
        let updated = subscription
            .get("updated")
            .and_then(Value::as_i64)
            .unwrap_or(0);
        let skipped = subscription
            .get("skipped")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let updated_label = if updated > 0 {
            format!("{} ago", elapsed_label(updated))
        } else {
            "never".to_string()
        };

        ui.add_space(8.0);
        ui.label(format!(
            "Last update: {updated_label}  -  skipped entries: {skipped}",
        ));

        ui.horizontal(|ui| {
            if ui
                .add_enabled(!self.action_busy, egui::Button::new("Refresh"))
                .clicked()
            {
                self.request_mutation(
                    "refresh",
                    vec![json!(id.clone())],
                    "Subscription refreshed",
                    true,
                );
            }

            if source_type == "url"
                && ui
                    .add_enabled(!self.action_busy, egui::Button::new("Edit"))
                    .clicked()
            {
                self.sync_edit_name();
                self.edit_mode = !self.edit_mode;
                self.confirm_delete = false;
            }

            if ui
                .add_enabled(!self.action_busy, egui::Button::new("Delete"))
                .clicked()
            {
                self.confirm_delete = true;
                self.edit_mode = false;
            }
        });

        if self.edit_mode && source_type == "url" {
            ui.group(|ui| {
                ui.strong("Edit subscription");
                ui.label("Name");
                ui.add(egui::TextEdit::singleline(&mut self.edit_name).char_limit(80));
                ui.label("New provider URL (leave empty to keep the saved URL)");
                ui.add(
                    egui::TextEdit::singleline(&mut self.edit_url)
                        .password(true)
                        .char_limit(8192),
                );

                if ui
                    .add_enabled(
                        !self.edit_name.trim().is_empty() && !self.action_busy,
                        egui::Button::new("Save changes"),
                    )
                    .clicked()
                {
                    self.request_mutation(
                        "edit",
                        vec![
                            json!(id.clone()),
                            json!(self.edit_name.trim()),
                            json!(self.edit_url.trim()),
                        ],
                        "Subscription updated",
                        true,
                    );
                }
            });
        }

        if self.confirm_delete {
            ui.group(|ui| {
                ui.colored_label(
                    egui::Color32::LIGHT_RED,
                    "Delete this subscription and its servers?",
                );

                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(!self.action_busy, egui::Button::new("Confirm delete"))
                        .clicked()
                    {
                        self.confirm_delete = false;
                        self.request_mutation(
                            "delete",
                            vec![json!(id)],
                            "Subscription deleted",
                            true,
                        );
                    }

                    if ui.button("Cancel").clicked() {
                        self.confirm_delete = false;
                    }
                });
            });
        }
    }

    fn ui_settings(&mut self, ui: &mut egui::Ui) {
        ui.heading("Settings");

        let channel = self
            .preferences
            .get("channel")
            .and_then(Value::as_str)
            .unwrap_or("stable")
            .to_string();
        let autostart = self
            .preferences
            .get("autostart")
            .and_then(Value::as_bool)
            .unwrap_or(false);

        ui.group(|ui| {
            ui.strong("Updates");
            ui.label("Stable receives normal releases. Preview receives prereleases too.");

            ui.horizontal(|ui| {
                for value in ["stable", "preview"] {
                    if ui
                        .add_enabled(
                            !self.action_busy,
                            egui::RadioButton::new(
                                channel == value,
                                if value == "stable" {
                                    "Stable"
                                } else {
                                    "Preview"
                                },
                            ),
                        )
                        .clicked()
                        && channel != value
                    {
                        self.request_mutation(
                            "set_preferences",
                            vec![json!({"channel": value})],
                            "Update channel changed",
                            false,
                        );
                    }
                }
            });
        });

        ui.add_space(8.0);
        ui.group(|ui| {
            ui.strong("Desktop Mode");
            let mut enabled = autostart;

            if ui
                .add_enabled(
                    !self.action_busy,
                    egui::Checkbox::new(&mut enabled, "Start DeckPort VPN with Desktop Mode"),
                )
                .changed()
            {
                match update_autostart_file(enabled) {
                    Ok(()) => {
                        self.request_mutation(
                            "set_preferences",
                            vec![json!({"autostart": enabled})],
                            "Desktop startup preference changed",
                            false,
                        );
                    }
                    Err(message) => {
                        self.error = message;
                    }
                }
            }
        });

        ui.add_space(8.0);
        ui.group(|ui| {
            ui.strong("Maintenance");

            ui.horizontal(|ui| {
                if ui.button("Open Setup").clicked() {
                    match open_setup_window() {
                        Ok(()) => {
                            self.notice = "Setup opened".to_string();
                            self.error.clear();
                        }
                        Err(message) => {
                            self.error = message;
                        }
                    }
                }

                if ui
                    .add_enabled(
                        !self.diagnostics_busy,
                        egui::Button::new(
                            if self.diagnostics_busy {
                                "Loading diagnostics..."
                            } else {
                                "Refresh safe diagnostics"
                            },
                        ),
                    )
                    .clicked()
                {
                    self.request_diagnostics();
                }
            });

            ui.label(
                "Diagnostics omit provider URLs, hosts, credentials, keys, and raw sing-box output.",
            );

            egui::ScrollArea::vertical()
                .max_height(250.0)
                .show(ui, |ui| {
                    if self.diagnostics.is_empty() {
                        ui.label("Diagnostics have not been loaded.");
                    } else {
                        ui.monospace(&self.diagnostics);
                    }
                });
        });
    }
}

impl eframe::App for DeckPortApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if let Some(setup) = self.setup.as_mut() {
            setup.ui(ui);
            ui.ctx().request_repaint_after(Duration::from_millis(150));
            return;
        }

        self.process_messages();

        if self.last_refresh.elapsed() >= Duration::from_secs(2) {
            self.request_refresh();
        }

        {
            let visuals = ui.visuals_mut();
            visuals.dark_mode = true;
            visuals.panel_fill = egui::Color32::from_rgb(6, 16, 25);
            visuals.window_fill = egui::Color32::from_rgb(7, 18, 27);
            visuals.faint_bg_color = egui::Color32::from_rgb(10, 28, 40);
            visuals.extreme_bg_color = egui::Color32::from_rgb(5, 13, 20);
            visuals.selection.bg_fill = egui::Color32::from_rgb(22, 88, 61);
            visuals.selection.stroke =
                egui::Stroke::new(1.0, egui::Color32::from_rgb(61, 240, 149));
            visuals.widgets.inactive.bg_fill = egui::Color32::from_rgb(14, 34, 48);
            visuals.widgets.hovered.bg_fill = egui::Color32::from_rgb(17, 48, 64);
            visuals.widgets.active.bg_fill = egui::Color32::from_rgb(18, 71, 51);
        }

        ui.horizontal(|ui| {
            egui::Frame::group(ui.style())
                .fill(egui::Color32::from_rgb(7, 20, 30))
                .stroke(egui::Stroke::new(1.0, egui::Color32::from_rgb(18, 43, 59)))
                .show(ui, |ui| self.ui_header(ui));

            ui.add_space(12.0);

            ui.vertical(|ui| {
                self.ui_feedback(ui);

                match self.page {
                    Page::Vpn => self.ui_vpn(ui),
                    Page::Servers => self.ui_servers(ui),
                    Page::Subscriptions => self.ui_subscriptions(ui),
                    Page::Settings => self.ui_settings(ui),
                }
            });
        });

        ui.ctx().request_repaint_after(Duration::from_millis(150));
    }
}

fn import_local_file() -> Result<Value, String> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/home/deck"));
    let output = if PathBuf::from("/usr/bin/kdialog").is_file() {
        Command::new("/usr/bin/kdialog")
            .arg("--getopenfilename")
            .arg(&home)
            .arg("*.txt *.conf *.json *.yaml *.yml")
            .output()
    } else {
        Command::new("/usr/bin/zenity")
            .arg("--file-selection")
            .arg("--title=Import DeckPort subscription")
            .arg("--file-filter=Subscriptions | *.txt *.conf *.json *.yaml *.yml")
            .output()
    }
    .map_err(|_| "No system file picker is available; use Import pasted text.".to_string())?;

    if !output.status.success() {
        return Ok(Value::Bool(false));
    }

    if output.stdout.len() > 16 * 1024 {
        return Err("The selected file path is invalid".to_string());
    }

    let path = String::from_utf8(output.stdout)
        .map(PathBuf::from)
        .map_err(|_| "The selected file path is invalid".to_string())?;
    let path = PathBuf::from(path.to_string_lossy().trim());

    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    if !["txt", "conf", "json", "yaml", "yml"].contains(&extension.as_str()) {
        return Err("Choose a supported subscription file".to_string());
    }

    use std::io::Read;
    use std::os::unix::fs::OpenOptionsExt;

    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(&path)
        .map_err(|_| "The selected file could not be read safely".to_string())?;
    let metadata = file
        .metadata()
        .map_err(|_| "The selected file could not be inspected".to_string())?;

    if !metadata.is_file() || metadata.len() > 4 * 1024 * 1024 {
        return Err("Choose a regular subscription file under 4 MiB".to_string());
    }

    let mut content = String::new();
    file.take(4 * 1024 * 1024 + 1)
        .read_to_string(&mut content)
        .map_err(|_| "The subscription file must contain UTF-8 text".to_string())?;

    if content.len() > 4 * 1024 * 1024 {
        return Err("The subscription file is too large".to_string());
    }

    let mut name = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Imported subscription")
        .chars()
        .take(80)
        .collect::<String>();

    if name.trim().is_empty() {
        name = "Imported subscription".to_string();
    }

    ipc::call("import_content", vec![json!(content), json!(name)])
}

fn update_autostart_file(enabled: bool) -> Result<(), String> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "The desktop account home could not be found".to_string())?;
    let directory = home.join(".config/autostart");
    let target = directory.join("deckport-vpn.desktop");

    if !enabled {
        match fs::remove_file(&target) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(());
            }
            Err(_) => {
                return Err("Desktop startup preference could not be saved".to_string());
            }
        }
    }

    fs::create_dir_all(&directory)
        .map_err(|_| "Desktop startup preference could not be saved".to_string())?;

    if fs::symlink_metadata(&target)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
    {
        return Err("Unsafe Desktop startup file".to_string());
    }

    let temporary = directory.join(format!(".deckport-vpn-{}.desktop", std::process::id()));
    let content = concat!(
        "[Desktop Entry]\n",
        "Type=Application\n",
        "Name=DeckPort VPN\n",
        "Exec=/var/lib/deckport-vpn/current/desktop/deckport\n",
        "Icon=deckport-vpn\n",
        "Terminal=false\n",
        "OnlyShowIn=KDE;\n",
        "X-KDE-autostart-after=panel\n"
    );

    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;

    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(|_| "Desktop startup preference could not be saved".to_string())?;

    let result = (|| -> Result<(), String> {
        file.write_all(content.as_bytes())
            .map_err(|_| "Desktop startup preference could not be saved".to_string())?;
        file.sync_all()
            .map_err(|_| "Desktop startup preference could not be saved".to_string())?;
        fs::rename(&temporary, &target)
            .map_err(|_| "Desktop startup preference could not be saved".to_string())?;
        Ok(())
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }

    result
}

fn open_setup_window() -> Result<(), String> {
    let executable = std::env::current_exe()
        .map_err(|_| "Could not locate the Desktop application".to_string())?;

    Command::new(executable)
        .arg("--setup")
        .spawn()
        .map(|_| ())
        .map_err(|_| "Could not open DeckPort Setup".to_string())
}

fn elapsed_label(timestamp: i64) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(timestamp);
    let seconds = now.saturating_sub(timestamp).max(0) as u64;

    if seconds < 60 {
        format!("{seconds}s")
    } else if seconds < 60 * 60 {
        format!("{}m", seconds / 60)
    } else if seconds < 24 * 60 * 60 {
        format!("{}h {}m", seconds / 3600, seconds / 60 % 60)
    } else {
        format!("{}d", seconds / 86400)
    }
}
