use crate::theme::Icon;
use crate::{ipc, setup, theme};
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
    daemon_online: bool,
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
            daemon_online: false,
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
            daemon_online: false,
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
                            self.daemon_online = true;
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
                            self.daemon_online = false;
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
        ui.set_min_height(ui.available_height());
        ui.add_space(18.0);
        ui.horizontal(|ui| {
            let (rect, _) = ui.allocate_exact_size(egui::vec2(42.0, 52.0), egui::Sense::hover());
            theme::paint_icon(
                ui.painter(),
                Icon::Shield,
                rect.center(),
                42.0,
                theme::GREEN,
            );
            ui.vertical(|ui| {
                ui.label(egui::RichText::new("DeckPort").size(25.0).strong());
                ui.label(
                    egui::RichText::new("Your Privacy. Your Way.")
                        .size(12.0)
                        .color(theme::MUTED),
                );
            });
        });
        ui.add_space(34.0);
        for (page, icon, label) in [
            (Page::Vpn, Icon::Home, "Home"),
            (Page::Servers, Icon::Servers, "Servers"),
            (Page::Subscriptions, Icon::Link, "Subscriptions"),
            (Page::Settings, Icon::Settings, "Settings"),
        ] {
            if theme::nav(ui, icon, label, self.page == page).clicked() {
                self.page = page;
            }
            ui.add_space(3.0);
        }
        ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
            ui.add_space(14.0);
            ui.label(
                egui::RichText::new(format!("v{VERSION}  ·  SteamOS"))
                    .size(12.0)
                    .color(theme::DIM),
            );
            theme::status_dot(
                ui,
                if self.daemon_online {
                    "Connected to core"
                } else if self.refresh_busy {
                    "Connecting to core…"
                } else {
                    "Core unavailable"
                },
                if self.daemon_online {
                    theme::GREEN
                } else {
                    theme::AMBER
                },
            );
        });
    }

    fn ui_feedback(&mut self, ui: &mut egui::Ui) {
        if !self.error.is_empty() {
            egui::Frame::new()
                .fill(egui::Color32::from_rgb(43, 25, 32))
                .corner_radius(10)
                .inner_margin(12)
                .show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    ui.colored_label(theme::RED, &self.error);
                });
            ui.add_space(6.0);
        }
        if !self.notice.is_empty() {
            ui.horizontal_wrapped(|ui| {
                ui.colored_label(theme::GREEN, &self.notice);
                if ui.small_button("Dismiss").clicked() {
                    self.notice.clear();
                }
            });
            ui.add_space(6.0);
        }
    }

    fn connection_server(&self) -> Value {
        let active = self.daemon_online
            && matches!(
                self.state(),
                "CONNECTED" | "CONNECTING" | "RECONNECTING" | "DISCONNECTING"
            );
        let selected = self
            .status
            .get("selected_server")
            .filter(|value| !value.is_null());
        let server = self.status.get("server").filter(|value| !value.is_null());
        if active {
            server.or(selected)
        } else {
            selected
        }
        .cloned()
        .unwrap_or(Value::Null)
    }

    fn ui_vpn(&mut self, ui: &mut egui::Ui) {
        if ui.available_width() >= 780.0 {
            let right_width = (ui.available_width() * 0.32).clamp(278.0, 330.0);
            let main_width = ui.available_width() - right_width - 24.0;
            ui.horizontal_top(|ui| {
                ui.allocate_ui_with_layout(
                    egui::vec2(main_width, 530.0),
                    egui::Layout::top_down(egui::Align::Center),
                    |ui| {
                        self.ui_connection_stage(ui);
                    },
                );
                ui.add_space(14.0);
                ui.vertical(|ui| {
                    ui.set_width(right_width);
                    self.ui_connection_details(ui);
                });
            });
        } else {
            self.ui_connection_stage(ui);
            ui.add_space(20.0);
            self.ui_connection_details(ui);
        }
    }

    fn ui_connection_stage(&mut self, ui: &mut egui::Ui) {
        let state = self.state().to_string();
        let connected = self.daemon_online && state == "CONNECTED";
        let transitioning = self.daemon_online
            && matches!(
                state.as_str(),
                "CONNECTING" | "RECONNECTING" | "DISCONNECTING"
            );
        let server = self.connection_server();
        let name = server
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("Choose a server");
        let protocol = server
            .get("protocol")
            .and_then(Value::as_str)
            .unwrap_or("—")
            .to_uppercase();
        let country = server.get("country").and_then(Value::as_str).unwrap_or("");
        let latency = server
            .get("id")
            .and_then(Value::as_str)
            .map(|id| self.ping_label(id))
            .unwrap_or_else(|| "—".into());
        let accent = if connected {
            theme::GREEN
        } else if transitioning {
            theme::AMBER
        } else {
            theme::MUTED
        };
        let map_rect = egui::Rect::from_min_size(
            ui.cursor().min + egui::vec2(0.0, 72.0),
            egui::vec2(ui.available_width(), 350.0),
        );
        theme::world_map(ui.painter(), map_rect);
        ui.vertical_centered(|ui| {
            ui.add_space(8.0);
            egui::Frame::new()
                .fill(if connected {
                    theme::GREEN_DARK
                } else {
                    theme::SURFACE
                })
                .stroke(egui::Stroke::new(
                    1.0,
                    if connected {
                        egui::Color32::from_rgb(37, 91, 68)
                    } else {
                        theme::BORDER
                    },
                ))
                .corner_radius(24)
                .inner_margin(egui::Margin::symmetric(16, 8))
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        let (rect, _) =
                            ui.allocate_exact_size(egui::vec2(17.0, 20.0), egui::Sense::hover());
                        theme::paint_icon(
                            ui.painter(),
                            if connected { Icon::Lock } else { Icon::Shield },
                            rect.center(),
                            16.0,
                            accent,
                        );
                        ui.label(
                            egui::RichText::new(if connected {
                                "Secure Connection"
                            } else if transitioning {
                                "Connection in progress"
                            } else {
                                "Your private connection"
                            })
                            .size(14.0)
                            .color(accent),
                        );
                    });
                });
            ui.add_space(52.0);
            let action_label = power_action_label(
                &state,
                self.daemon_online,
                self.selected_server_id().is_some(),
            );
            let response = ui.add_enabled(
                self.daemon_online && !self.action_busy,
                egui::Button::new("")
                    .fill(egui::Color32::TRANSPARENT)
                    .stroke(egui::Stroke::NONE)
                    .min_size(egui::vec2(218.0, 218.0))
                    .corner_radius(109),
            );
            response.widget_info(|| {
                egui::WidgetInfo::labeled(
                    egui::WidgetType::Button,
                    self.daemon_online && !self.action_busy,
                    action_label,
                )
            });
            let center = response.rect.center();
            let painter = ui.painter();
            theme::glow(painter, center, 92.0, connected);
            painter.circle_filled(center, 104.0, theme::BACKGROUND);
            painter.circle_stroke(
                center,
                104.0,
                egui::Stroke::new(
                    1.0,
                    if connected {
                        egui::Color32::from_rgb(32, 98, 69)
                    } else {
                        theme::BORDER
                    },
                ),
            );
            painter.circle_filled(
                center,
                94.0,
                if connected {
                    egui::Color32::from_rgb(9, 36, 28)
                } else {
                    theme::SURFACE
                },
            );
            painter.circle_stroke(
                center,
                94.0,
                egui::Stroke::new(
                    if response.hovered() || response.has_focus() {
                        4.0
                    } else {
                        2.5
                    },
                    accent,
                ),
            );
            if connected {
                painter.circle_stroke(
                    center,
                    90.0,
                    egui::Stroke::new(1.0, egui::Color32::from_rgb(41, 91, 62)),
                );
            }
            theme::paint_icon(painter, Icon::Power, center, 60.0, accent);
            if transitioning || self.action_busy {
                ui.ctx().request_repaint_after(Duration::from_millis(80));
                ui.spinner();
            }
            let clicked = response.on_hover_text(action_label).clicked();
            if clicked {
                if matches!(
                    state.as_str(),
                    "CONNECTED" | "CONNECTING" | "RECONNECTING" | "DISCONNECTING" | "ERROR"
                ) {
                    self.request_mutation("disconnect", vec![], "VPN disconnected", false);
                } else if let Some(id) = self.selected_server_id().map(str::to_owned) {
                    self.request_mutation("connect", vec![json!(id)], "Connection started", false);
                } else {
                    self.page = Page::Servers;
                }
            }
            ui.add_space(8.0);
            ui.label(
                egui::RichText::new(connection_title(&state, self.daemon_online))
                    .size(25.0)
                    .strong()
                    .color(accent),
            );
            ui.label(
                egui::RichText::new(if connected {
                    connection_uptime(self.status.get("since").and_then(Value::as_i64))
                } else {
                    action_label.to_string()
                })
                .size(14.0)
                .color(theme::MUTED),
            );
            ui.add_space(12.0);

            let width = ui.available_width().min(350.0);
            let response = ui.add_sized(
                [width, 65.0],
                egui::Button::new("").fill(theme::SURFACE).corner_radius(16),
            );
            response.widget_info(|| {
                egui::WidgetInfo::labeled(
                    egui::WidgetType::Button,
                    true,
                    format!("Change server: {name}"),
                )
            });
            let rect = response.rect;
            theme::country_badge(
                ui.painter(),
                egui::pos2(rect.left() + 32.0, rect.center().y),
                country,
            );
            theme::text(
                ui.painter(),
                egui::pos2(rect.left() + 61.0, rect.center().y - 10.0),
                name,
                16.0,
                theme::TEXT,
                rect.right() - 36.0,
            );
            theme::text(
                ui.painter(),
                egui::pos2(rect.left() + 61.0, rect.center().y + 13.0),
                &format!("{protocol}  ·  {latency}"),
                13.0,
                theme::MUTED,
                rect.right() - 36.0,
            );
            theme::paint_icon(
                ui.painter(),
                Icon::Chevron,
                egui::pos2(rect.right() - 21.0, rect.center().y),
                18.0,
                theme::MUTED,
            );
            if response.on_hover_text(name).clicked() {
                self.page = Page::Servers;
            }

            ui.add_space(18.0);
            theme::card().show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.columns(3, |columns| {
                    for (column, (icon, value, label)) in columns.iter_mut().zip([
                        (
                            Icon::Clock,
                            if connected {
                                connection_uptime(self.status.get("since").and_then(Value::as_i64))
                            } else {
                                "—".into()
                            },
                            "Uptime",
                        ),
                        (Icon::Shield, protocol, "Protocol"),
                        (Icon::Activity, latency, "TCP latency"),
                    ]) {
                        column.vertical_centered(|ui| {
                            let (rect, _) = ui
                                .allocate_exact_size(egui::vec2(24.0, 24.0), egui::Sense::hover());
                            theme::paint_icon(
                                ui.painter(),
                                icon,
                                rect.center(),
                                21.0,
                                theme::GREEN,
                            );
                            ui.label(egui::RichText::new(value).size(16.0));
                            ui.label(egui::RichText::new(label).size(13.0).color(theme::MUTED));
                        });
                    }
                });
            });
        });
    }

    fn ui_connection_details(&mut self, ui: &mut egui::Ui) {
        let connected = self.daemon_online && self.state() == "CONNECTED";
        let server = self.connection_server();
        let protocol = server
            .get("protocol")
            .and_then(Value::as_str)
            .unwrap_or("—")
            .to_uppercase();
        let name = server
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("Not selected");
        let latency = server
            .get("id")
            .and_then(Value::as_str)
            .map(|id| self.ping_label(id))
            .unwrap_or_else(|| "—".into());
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            theme::section(ui, "Connection");
            theme::key_value(ui, "Protocol", &protocol);
            theme::key_value(ui, "Server", name);
            theme::key_value(ui, "Ping", &latency);
            theme::key_value(
                ui,
                "Uptime",
                &if connected {
                    connection_uptime(self.status.get("since").and_then(Value::as_i64))
                } else {
                    "—".into()
                },
            );
            theme::key_value(
                ui,
                "Public IP",
                if connected {
                    self.status
                        .get("public_ip")
                        .and_then(Value::as_str)
                        .unwrap_or("Not verified")
                } else {
                    "—"
                },
            );
        });
        ui.add_space(8.0);
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            theme::section(ui, "Quick Actions");
            if theme::action(ui, Icon::Servers, "Change Server").clicked() {
                self.page = Page::Servers;
            }
            if ui
                .add_enabled_ui(!self.refresh_busy, |ui| {
                    theme::action(
                        ui,
                        Icon::Refresh,
                        if self.refresh_busy {
                            "Refreshing…"
                        } else {
                            "Refresh Status"
                        },
                    )
                })
                .inner
                .clicked()
            {
                self.request_refresh();
            }
            if theme::action(ui, Icon::Settings, "Connection Settings").clicked() {
                self.page = Page::Settings;
            }
        });
        ui.add_space(8.0);
        theme::card()
            .fill(if connected {
                egui::Color32::from_rgb(11, 31, 30)
            } else {
                theme::SURFACE
            })
            .show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.horizontal_top(|ui| {
                    let (rect, _) =
                        ui.allocate_exact_size(egui::vec2(37.0, 46.0), egui::Sense::hover());
                    theme::paint_icon(
                        ui.painter(),
                        Icon::Shield,
                        rect.center(),
                        34.0,
                        if connected {
                            theme::GREEN
                        } else {
                            theme::MUTED
                        },
                    );
                    ui.vertical(|ui| {
                        ui.label(
                            egui::RichText::new(if connected {
                                "Your VPN tunnel is active"
                            } else {
                                "Your VPN is not connected"
                            })
                            .size(14.0)
                            .strong()
                            .color(if connected {
                                theme::GREEN
                            } else {
                                theme::TEXT
                            }),
                        );
                        ui.label(
                            egui::RichText::new(if connected {
                                "Traffic is routed through your selected VPN server."
                            } else if self.daemon_online {
                                "Choose a server, then press the power button."
                            } else {
                                "Start the DeckPort service to connect."
                            })
                            .size(13.0)
                            .color(theme::MUTED),
                        );
                    });
                });
                if connected {
                    let verification = self
                        .status
                        .get("verification")
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    ui.add_space(4.0);
                    ui.label(
                        egui::RichText::new(match verification {
                            "verified" => "Public IP change verified.",
                            "same_ip" => "Public IP has not changed. Check your provider.",
                            _ => "Public IP verification is informational.",
                        })
                        .size(12.0)
                        .color(theme::MUTED),
                    );
                }
            });
    }

    fn ui_servers(&mut self, ui: &mut egui::Ui) {
        theme::heading(ui, "Servers", "Find your next connection.");

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
            theme::card().show(ui, |ui| {
                theme::section(ui, "Your servers will appear here");
                ui.label(
                    egui::RichText::new(
                        "Add a subscription URL or import a local file to get started.",
                    )
                    .color(theme::MUTED),
                );
            });

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

        ui.horizontal_wrapped(|ui| {
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

        ui.horizontal_wrapped(|ui| {
            let search_width = (ui.available_width() - 285.0).clamp(170.0, 430.0);
            ui.add(
                egui::TextEdit::singleline(&mut self.search)
                    .desired_width(search_width)
                    .hint_text("Search servers…"),
            );
            egui::ComboBox::from_id_salt("server_sort")
                .selected_text(match self.sort_mode {
                    SortMode::Default => "Default order",
                    SortMode::Latency => "Lowest ping",
                    SortMode::Name => "Name A–Z",
                })
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.sort_mode, SortMode::Default, "Default order");
                    ui.selectable_value(&mut self.sort_mode, SortMode::Latency, "Lowest ping");
                    ui.selectable_value(&mut self.sort_mode, SortMode::Name, "Name A–Z");
                });
            ui.checkbox(&mut self.favorites_only, "Favorites");
        });
        ui.add_space(12.0);

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

        ui.label(
            egui::RichText::new(format!("{} servers", servers.len()))
                .size(13.0)
                .color(theme::MUTED),
        );
        if servers.is_empty() {
            theme::card().show(ui, |ui| {
                theme::section(
                    ui,
                    if self.loading_subscription.is_some() {
                        "Loading servers…"
                    } else {
                        "No matching servers"
                    },
                );
                ui.label(
                    egui::RichText::new(
                        "Try a different search, turn off Favorites, or refresh the subscription.",
                    )
                    .color(theme::MUTED),
                );
            });
        }
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
            let ping_color = match self.latency(&id) {
                u64::MAX => theme::DIM,
                0..=79 => theme::GREEN,
                80..=149 => theme::AMBER,
                _ => theme::RED,
            };
            ui.push_id(&id, |ui| {
                ui.horizontal(|ui| {
                    let width = (ui.available_width() - 48.0).max(180.0);
                    let response = ui.add_enabled(
                        !self.action_busy,
                        egui::Button::new("")
                            .min_size(egui::vec2(width, 68.0))
                            .corner_radius(12)
                            .fill(if selected {
                                theme::GREEN_DARK
                            } else {
                                theme::SURFACE
                            })
                            .stroke(egui::Stroke::new(
                                1.0,
                                if selected {
                                    egui::Color32::from_rgb(44, 98, 74)
                                } else {
                                    theme::BORDER
                                },
                            )),
                    );
                    response.widget_info(|| {
                        egui::WidgetInfo::selected(
                            egui::WidgetType::SelectableLabel,
                            !self.action_busy,
                            selected,
                            format!("{name}, {protocol}, {ping}"),
                        )
                    });
                    let rect = response.rect;
                    theme::country_badge(
                        ui.painter(),
                        egui::pos2(rect.left() + 30.0, rect.center().y),
                        country,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(rect.left() + 60.0, rect.center().y - 10.0),
                        name,
                        16.0,
                        theme::TEXT,
                        rect.right() - 100.0,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(rect.left() + 60.0, rect.center().y + 13.0),
                        &format!("{protocol}{}", if selected { "  ·  Selected" } else { "" }),
                        13.0,
                        theme::MUTED,
                        rect.right() - 100.0,
                    );
                    ui.painter().circle_filled(
                        egui::pos2(rect.right() - 90.0, rect.center().y),
                        3.0,
                        ping_color,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(rect.right() - 80.0, rect.center().y),
                        &ping,
                        13.0,
                        ping_color,
                        rect.right() - 7.0,
                    );
                    if response.on_hover_text(name).clicked() {
                        select_server = Some(id.clone());
                    }
                    if ui
                        .add_enabled_ui(!self.action_busy, |ui| {
                            theme::icon_button(
                                ui,
                                Icon::Star,
                                if favorite {
                                    "Remove from favorites"
                                } else {
                                    "Add to favorites"
                                },
                                favorite,
                            )
                        })
                        .inner
                        .clicked()
                    {
                        favorite_change = Some((id.clone(), !favorite));
                    }
                });
            });
        }

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
        theme::heading(ui, "Subscriptions", "Manage your VPN subscriptions.");

        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(!self.action_busy, theme::primary("+  Add Subscription"))
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

        for (id, name, count, source) in &subscriptions {
            let selected = self.selected_subscription.as_deref() == Some(id.as_str());
            let updated = self
                .subscriptions
                .iter()
                .find(|item| item.get("id").and_then(Value::as_str) == Some(id.as_str()))
                .and_then(|item| item.get("updated"))
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let updated_label = if updated > 0 {
                format!("Updated {} ago", elapsed_label(updated))
            } else {
                "Not refreshed yet".to_string()
            };
            ui.push_id(id, |ui| {
                ui.horizontal(|ui| {
                    let width = (ui.available_width() - 48.0).max(200.0);
                    let response = ui.add_sized(
                        [width, 92.0],
                        egui::Button::new("")
                            .fill(if selected {
                                theme::RAISED
                            } else {
                                theme::SURFACE
                            })
                            .stroke(egui::Stroke::new(
                                1.0,
                                if selected {
                                    egui::Color32::from_rgb(45, 85, 71)
                                } else {
                                    theme::BORDER
                                },
                            ))
                            .corner_radius(14),
                    );
                    response.widget_info(|| {
                        egui::WidgetInfo::selected(
                            egui::WidgetType::SelectableLabel,
                            true,
                            selected,
                            format!("{name}, {count} servers"),
                        )
                    });
                    let rect = response.rect;
                    theme::paint_icon(
                        ui.painter(),
                        Icon::Link,
                        egui::pos2(rect.left() + 30.0, rect.center().y),
                        25.0,
                        if selected { theme::GREEN } else { theme::MUTED },
                    );
                    let left = rect.left() + 59.0;
                    let right = rect.right() - 101.0;
                    theme::text(
                        ui.painter(),
                        egui::pos2(left, rect.center().y - 23.0),
                        name,
                        16.0,
                        theme::TEXT,
                        right,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(left, rect.center().y),
                        if source == "url" {
                            "Private subscription URL"
                        } else {
                            "Local subscription"
                        },
                        13.0,
                        theme::MUTED,
                        right,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(left, rect.center().y + 23.0),
                        &updated_label,
                        12.0,
                        theme::DIM,
                        right,
                    );
                    theme::text(
                        ui.painter(),
                        egui::pos2(rect.right() - 93.0, rect.center().y),
                        &format!("{count} servers"),
                        13.0,
                        theme::MUTED,
                        rect.right() - 7.0,
                    );
                    if response.on_hover_text(name).clicked() {
                        choose = Some(id.clone());
                    }
                    if ui
                        .add_enabled_ui(!self.action_busy, |ui| {
                            theme::icon_button(ui, Icon::Refresh, "Refresh subscription", false)
                        })
                        .inner
                        .clicked()
                    {
                        self.request_mutation(
                            "refresh",
                            vec![json!(id.clone())],
                            "Subscription refreshed",
                            true,
                        );
                    }
                });
            });
        }
        ui.add_space(10.0);

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
        theme::heading(ui, "Settings", "Make DeckPort feel at home.");
        theme::section(ui, "General");
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            let mut enabled = self
                .preferences
                .get("autostart")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            if theme::setting(
                ui,
                Icon::Power,
                "Start with Desktop Mode",
                "Launch DeckPort when your desktop starts.",
                &mut enabled,
                self.daemon_online && !self.action_busy,
            ) {
                match update_autostart_file(enabled) {
                    Ok(()) => self.request_mutation(
                        "set_preferences",
                        vec![json!({"autostart": enabled})],
                        "Desktop startup preference changed",
                        false,
                    ),
                    Err(message) => self.error = message,
                }
            }
            ui.separator();
            let mut unavailable = false;
            theme::setting(
                ui,
                Icon::Refresh,
                "Auto Connect",
                "Not supported by the current VPN core.",
                &mut unavailable,
                false,
            );
        });
        ui.add_space(10.0);
        theme::section(ui, "Connection");
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            let mut unavailable = false;
            theme::setting(
                ui,
                Icon::Shield,
                "Kill Switch",
                "Not supported. Traffic is not blocked when VPN is off.",
                &mut unavailable,
                false,
            );
            ui.separator();
            ui.horizontal_wrapped(|ui| {
                ui.label("Server latency");
                ui.label(
                    egui::RichText::new("Check real TCP latency on the Servers page.")
                        .size(14.0)
                        .color(theme::MUTED),
                );
                if ui.button("Open Servers").clicked() {
                    self.page = Page::Servers;
                }
            });
        });
        ui.add_space(10.0);
        theme::section(ui, "Updates");
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            let channel = self
                .preferences
                .get("channel")
                .and_then(Value::as_str)
                .unwrap_or("stable")
                .to_string();
            ui.horizontal_wrapped(|ui| {
                ui.label("Release channel");
                for (value, label) in [("stable", "Stable"), ("preview", "Preview")] {
                    if ui
                        .add_enabled(
                            self.daemon_online && !self.action_busy,
                            egui::RadioButton::new(channel == value, label),
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
            ui.label(
                egui::RichText::new(
                    "Preview includes prereleases. Stable is recommended for everyday use.",
                )
                .size(13.0)
                .color(theme::MUTED),
            );
        });
        ui.add_space(10.0);
        theme::section(ui, "Maintenance");
        theme::card().show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal_wrapped(|ui| {
                if ui.button("Open Setup").clicked() {
                    match open_setup_window() {
                        Ok(()) => { self.notice = "Setup opened".to_string(); self.error.clear(); }
                        Err(message) => self.error = message,
                    }
                }
                if ui.add_enabled(!self.diagnostics_busy && self.daemon_online, egui::Button::new(if self.diagnostics_busy { "Loading diagnostics…" } else { "Refresh safe diagnostics" })).clicked() {
                    self.request_diagnostics();
                }
            });
            ui.label(egui::RichText::new("Diagnostics omit provider URLs, hosts, credentials, keys, and raw sing-box output.").size(13.0).color(theme::MUTED));
            egui::CollapsingHeader::new("Safe diagnostics").default_open(!self.diagnostics.is_empty()).show(ui, |ui| {
                if self.diagnostics.is_empty() {
                    ui.label(egui::RichText::new("Diagnostics have not been loaded.").color(theme::DIM));
                } else {
                    ui.monospace(&self.diagnostics);
                }
            });
        });
    }

    fn ui_shell(&mut self, ui: &mut egui::Ui) {
        let area = ui.max_rect();
        let sidebar_width = if area.width() >= 1100.0 { 238.0 } else { 218.0 };
        let sidebar = egui::Rect::from_min_max(
            area.min,
            egui::pos2(area.left() + sidebar_width, area.bottom()),
        );
        ui.painter().rect_filled(area, 0, theme::BACKGROUND);
        ui.painter().rect_filled(sidebar, 0, theme::SIDEBAR);
        ui.painter().line_segment(
            [sidebar.right_top(), sidebar.right_bottom()],
            egui::Stroke::new(1.0, theme::BORDER),
        );
        ui.scope_builder(
            egui::UiBuilder::new()
                .id_salt("navigation")
                .max_rect(sidebar.shrink2(egui::vec2(16.0, 14.0))),
            |ui| self.ui_header(ui),
        );
        let content = egui::Rect::from_min_max(
            egui::pos2(sidebar.right() + 26.0, area.top() + 28.0),
            area.max - egui::vec2(26.0, 22.0),
        );
        ui.scope_builder(
            egui::UiBuilder::new().id_salt("content").max_rect(content),
            |ui| {
                egui::ScrollArea::vertical()
                    .id_salt(self.page as u8)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        self.ui_feedback(ui);
                        match self.page {
                            Page::Vpn => self.ui_vpn(ui),
                            Page::Servers => self.ui_servers(ui),
                            Page::Subscriptions => self.ui_subscriptions(ui),
                            Page::Settings => self.ui_settings(ui),
                        }
                    });
            },
        );
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
        self.ui_shell(ui);
        ui.ctx().request_repaint_after(Duration::from_millis(150));
    }
}

fn connection_title(state: &str, online: bool) -> &'static str {
    if !online {
        return "Core unavailable";
    }
    match state {
        "CONNECTED" => "Connected",
        "CONNECTING" => "Connecting…",
        "RECONNECTING" => "Reconnecting…",
        "DISCONNECTING" => "Disconnecting…",
        "ERROR" => "Connection error",
        "DISCONNECTED" => "Disconnected",
        _ => "Checking connection…",
    }
}

fn power_action_label(state: &str, online: bool, selected: bool) -> &'static str {
    if !online {
        return "Waiting for the DeckPort service";
    }
    match state {
        "CONNECTED" => "Disconnect VPN",
        "CONNECTING" | "RECONNECTING" => "Cancel connection",
        "DISCONNECTING" => "Disconnect VPN",
        "ERROR" => "Reset connection",
        _ if selected => "Connect VPN",
        _ => "Choose a server to connect",
    }
}

fn connection_uptime(since: Option<i64>) -> String {
    let Some(since) = since.filter(|since| *since > 0) else {
        return "—".into();
    };
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(since);
    duration_label(now.saturating_sub(since).max(0) as u64)
}

fn duration_label(seconds: u64) -> String {
    format!(
        "{:02}:{:02}:{:02}",
        seconds / 3600,
        seconds / 60 % 60,
        seconds % 60
    )
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

#[cfg(test)]
mod tests {
    use super::*;

    fn offline_app() -> DeckPortApp {
        // Setup construction does not start IPC workers or touch user settings.
        let mut app = DeckPortApp::new_setup();
        app.setup = None;
        app
    }

    #[test]
    fn connection_labels_preserve_transitional_and_offline_states() {
        assert_eq!(connection_title("CONNECTED", false), "Core unavailable");
        assert_eq!(connection_title("CONNECTED", true), "Connected");
        assert_eq!(connection_title("CONNECTING", true), "Connecting…");
        assert_eq!(connection_title("RECONNECTING", true), "Reconnecting…");
        assert_eq!(connection_title("DISCONNECTING", true), "Disconnecting…");
        assert_eq!(connection_title("ERROR", true), "Connection error");
    }

    #[test]
    fn power_button_describes_the_actual_action() {
        assert_eq!(
            power_action_label("CONNECTED", true, true),
            "Disconnect VPN"
        );
        assert_eq!(
            power_action_label("CONNECTING", true, true),
            "Cancel connection"
        );
        assert_eq!(power_action_label("ERROR", true, true), "Reset connection");
        assert_eq!(
            power_action_label("DISCONNECTED", true, true),
            "Connect VPN"
        );
        assert_eq!(
            power_action_label("DISCONNECTED", true, false),
            "Choose a server to connect"
        );
    }

    #[test]
    fn uptime_is_a_clock_and_missing_data_is_not_fabricated() {
        assert_eq!(duration_label(754), "00:12:34");
        assert_eq!(duration_label(3661), "01:01:01");
        assert_eq!(duration_label(360_000), "100:00:00");
        assert_eq!(connection_uptime(None), "—");
        assert_eq!(connection_uptime(Some(0)), "—");
    }

    #[test]
    fn disconnected_view_does_not_reuse_the_previous_active_server() {
        let mut app = offline_app();
        app.daemon_online = true;
        app.status = json!({"state": "DISCONNECTED", "server": {"name": "Old"}, "selected_server": {"name": "Next"}});
        assert_eq!(app.connection_server()["name"], "Next");
        app.status["state"] = json!("CONNECTED");
        assert_eq!(app.connection_server()["name"], "Old");
    }

    #[test]
    fn losing_the_daemon_does_not_claim_a_secure_connection() {
        let mut app = offline_app();
        app.daemon_online = true;
        app.status = json!({"state": "CONNECTED"});
        app.tx
            .send(WorkerMessage::Snapshot(Err("Service unavailable".into())))
            .unwrap();
        app.process_messages();
        assert!(!app.daemon_online);
        assert_eq!(
            connection_title(app.state(), app.daemon_online),
            "Core unavailable"
        );
    }

    #[test]
    fn all_pages_render_at_desktop_and_minimum_window_sizes() {
        for size in [[1280.0, 760.0], [800.0, 560.0]] {
            for page in [
                Page::Vpn,
                Page::Servers,
                Page::Subscriptions,
                Page::Settings,
            ] {
                let mut app = offline_app();
                app.page = page;
                let ctx = egui::Context::default();
                theme::apply(&ctx);
                for _ in 0..3 {
                    let output = ctx.run_ui(
                        egui::RawInput {
                            screen_rect: Some(egui::Rect::from_min_size(
                                egui::Pos2::ZERO,
                                egui::vec2(size[0], size[1]),
                            )),
                            ..Default::default()
                        },
                        |ui| app.ui_shell(ui),
                    );
                    assert!(!output.shapes.is_empty());
                    output.drop_without_applying_deltas();
                }
            }
        }
    }
}
