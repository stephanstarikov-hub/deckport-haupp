mod ipc;
mod setup;

use eframe::egui;
use serde_json::{json, Value};
use std::time::{Duration, Instant};

const VERSION: &str = env!("CARGO_PKG_VERSION");

struct DeckPortApp {
    status: Value,
    subscriptions: Vec<Value>,
    servers: Vec<Value>,
    selected_subscription: Option<String>,
    search: String,
    error: String,
    last_refresh: Instant,
    setup: Option<setup::SetupState>,
}

impl DeckPortApp {
    fn new() -> Self {
        let mut app = Self {
            status: json!({}),
            subscriptions: Vec::new(),
            servers: Vec::new(),
            selected_subscription: None,
            search: String::new(),
            error: String::new(),
            last_refresh: Instant::now() - Duration::from_secs(10),
            setup: None,
        };

        app.refresh();
        app
    }

    fn new_setup() -> Self {
        Self {
            status: json!({}),
            subscriptions: Vec::new(),
            servers: Vec::new(),
            selected_subscription: None,
            search: String::new(),
            error: String::new(),
            last_refresh: Instant::now(),
            setup: Some(setup::SetupState::new()),
        }
    }

    fn refresh(&mut self) {
        let result = (|| -> Result<(Value, Vec<Value>), String> {
            let status = ipc::call("status", vec![])?;

            let subscriptions = ipc::call(
                "subscriptions",
                vec![],
            )?
            .as_array()
            .cloned()
            .ok_or_else(|| {
                "Invalid subscriptions response".to_string()
            })?;

            Ok((status, subscriptions))
        })();

        self.last_refresh = Instant::now();

        match result {
            Ok((status, subscriptions)) => {
                self.error.clear();
                self.status = status;
                self.subscriptions = subscriptions;

                let valid = self
                    .selected_subscription
                    .as_ref()
                    .map(|selected| {
                        self.subscriptions.iter().any(|item| {
                            item.get("id").and_then(Value::as_str)
                                == Some(selected.as_str())
                        })
                    })
                    .unwrap_or(false);

                if !valid {
                    self.selected_subscription = self
                        .subscriptions
                        .first()
                        .and_then(|item| {
                            item.get("id").and_then(Value::as_str)
                        })
                        .map(str::to_owned);

                    self.load_servers();
                }
            }

            Err(message) => {
                self.error = message;
            }
        }
    }

    fn load_servers(&mut self) {
        let Some(id) = self.selected_subscription.clone()
        else {
            self.servers.clear();
            return;
        };

        match ipc::call("servers", vec![json!(id)]) {
            Ok(value) => {
                if let Some(items) = value.as_array() {
                    self.servers = items.clone();
                    self.error.clear();
                } else {
                    self.error =
                        "Invalid servers response".to_string();
                }
            }

            Err(message) => {
                self.error = message;
            }
        }
    }

    fn action(&mut self, method: &str, args: Vec<Value>) {
        match ipc::call(method, args) {
            Ok(_) => self.refresh(),
            Err(message) => self.error = message,
        }
    }

    fn state(&self) -> &str {
        self.status
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("UNKNOWN")
    }

    fn selected_server(&self) -> Option<&str> {
        self.status
            .get("selected")
            .and_then(Value::as_str)
    }
}
impl eframe::App for DeckPortApp {
    fn ui(
        &mut self,
        ui: &mut egui::Ui,
        _frame: &mut eframe::Frame,
    ) {
        if let Some(setup) = self.setup.as_mut() {
            setup.ui(ui);
            return;
        }

        if self.last_refresh.elapsed() >= Duration::from_secs(2) {
            self.refresh();
        }

        ui.horizontal(|ui| {
            ui.heading("DeckPort VPN");
            ui.separator();
            ui.label(format!("v{VERSION}"));
        });

        ui.horizontal(|ui| {
            ui.strong(self.state().replace('_', " "));

            if let Some(ip) = self
                .status
                .get("public_ip")
                .and_then(Value::as_str)
            {
                ui.label(format!("Public IP: {ip}"));
            }
        });

        if !self.error.is_empty() {
            ui.colored_label(
                egui::Color32::LIGHT_RED,
                &self.error,
            );
        }

        let state = self.state().to_string();
        let selected = self.selected_server().map(str::to_owned);

        ui.horizontal(|ui| {
            let can_connect =
                selected.is_some()
                && matches!(
                    state.as_str(),
                    "DISCONNECTED" | "ERROR"
                );

            if ui
                .add_enabled(
                    can_connect,
                    egui::Button::new("Connect"),
                )
                .clicked()
            {
                if let Some(id) = selected.clone() {
                    self.action(
                        "connect",
                        vec![json!(id)],
                    );
                }
            }

            if ui
                .add_enabled(
                    state != "DISCONNECTED",
                    egui::Button::new("Disconnect"),
                )
                .clicked()
            {
                self.action("disconnect", vec![]);
            }

            if ui.button("Refresh").clicked() {
                self.refresh();
            }
        });

        ui.separator();

        ui.columns(2, |columns| {
            columns[0].heading("Subscriptions");

            let mut change_subscription = None;

            for subscription in &self.subscriptions {
                let Some(id) = subscription
                    .get("id")
                    .and_then(Value::as_str)
                else {
                    continue;
                };

                let name = subscription
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("Subscription");

                let count = subscription
                    .get("count")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);

                let selected =
                    self.selected_subscription.as_deref()
                        == Some(id);

                if columns[0]
                    .selectable_label(
                        selected,
                        format!("{name} ({count})"),
                    )
                    .clicked()
                {
                    change_subscription = Some(id.to_owned());
                }
            }

            if let Some(id) = change_subscription {
                self.selected_subscription = Some(id);
                self.load_servers();
            }

            columns[1].heading("Servers");

            columns[1].add(
                egui::TextEdit::singleline(&mut self.search)
                    .hint_text("Search servers"),
            );

            let query = self.search.to_lowercase();
            let mut choose_server = None;

            egui::ScrollArea::vertical()
                .show(&mut columns[1], |ui| {
                    for server in &self.servers {
                        let Some(id) =
                            server.get("id").and_then(Value::as_str)
                        else {
                            continue;
                        };

                        let name = server
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or("Unnamed server");

                        if !query.is_empty()
                            && !name.to_lowercase().contains(&query)
                        {
                            continue;
                        }

                        let protocol = server
                            .get("protocol")
                            .and_then(Value::as_str)
                            .unwrap_or("?")
                            .to_uppercase();

                        if ui
                            .selectable_label(
                                self.selected_server() == Some(id),
                                format!("{name}    {protocol}"),
                            )
                            .clicked()
                        {
                            choose_server = Some(id.to_owned());
                        }
                    }
                });

            if let Some(id) = choose_server {
                self.action("select", vec![json!(id)]);
            }
        });
    }
}

fn run_cli_action(argument: &str) -> Result<bool, String> {
    match argument {
        "--connect" => {
            let status = ipc::call("status", vec![])?;

            let selected = status
                .get("selected")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    "No VPN server is selected".to_string()
                })?
                .to_owned();

            ipc::call(
                "connect",
                vec![json!(selected)],
            )?;

            Ok(true)
        }

        "--disconnect" => {
            ipc::call("disconnect", vec![])?;
            Ok(true)
        }

        _ => Ok(false),
    }
}
fn main() -> eframe::Result {
    let mut setup_mode = false;

    if let Some(argument) = std::env::args().nth(1) {
        if argument == "--setup" {
            setup_mode = true;
        } else {
            match run_cli_action(&argument) {
                Ok(true) => return Ok(()),
                Ok(false) => {}
                Err(message) => {
                    eprintln!("DeckPort VPN: {message}");
                    return Ok(());
                }
            }
        }
    }

    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([960.0, 680.0])
            .with_min_inner_size([760.0, 520.0]),
        ..Default::default()
    };

    eframe::run_native(
        "DeckPort VPN",
        options,
        Box::new(move |_| {
            let app = if setup_mode {
                DeckPortApp::new_setup()
            } else {
                DeckPortApp::new()
            };

            Ok(Box::new(app))
        }),
    )
}
