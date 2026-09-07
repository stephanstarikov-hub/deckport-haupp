use eframe::egui;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::thread;

const BASE: &str = "/var/lib/deckport-vpn";

pub struct SetupState {
    busy: bool,
    confirm_uninstall: bool,
    status: String,
    output: String,
    receiver: Option<Receiver<Result<String, String>>>,
}

impl SetupState {
    pub fn new() -> Self {
        Self {
            busy: false,
            confirm_uninstall: false,
            status: concat!(
                "Repair reinstalls the current verified payload ",
                "without removing subscriptions or settings."
            )
            .to_string(),
            output: String::new(),
            receiver: None,
        }
    }

    fn start(&mut self, action: &'static str) {
        if self.busy {
            return;
        }

        let (sender, receiver) = mpsc::channel();

        self.busy = true;
        self.confirm_uninstall = false;
        self.status = "Waiting for system authorization".to_string();
        self.output.clear();
        self.receiver = Some(receiver);

        thread::spawn(move || {
            let result = run_installer(action);
            let _ = sender.send(result);
        });
    }

    fn poll(&mut self) {
        let result = self
            .receiver
            .as_ref()
            .and_then(|receiver| match receiver.try_recv() {
                Ok(result) => Some(result),
                Err(TryRecvError::Empty) => None,
                Err(TryRecvError::Disconnected) => {
                    Some(Err("Setup operation ended unexpectedly".to_string()))
                }
            });

        let Some(result) = result else {
            return;
        };

        self.receiver = None;
        self.busy = false;

        match result {
            Ok(message) => {
                self.status = "Operation completed successfully.".to_string();
                self.output = message;
            }
            Err(message) => {
                self.status = "Setup could not complete the operation.".to_string();
                self.output = message;
            }
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        self.poll();

        ui.heading("DeckPort VPN Setup");
        ui.label(format!(
            "Installed application version: {}",
            env!("DECKPORT_VERSION")
        ));

        ui.add_space(8.0);
        ui.label(&self.status);

        if self.busy {
            ui.add_space(8.0);
            ui.spinner();
        }

        ui.add_space(12.0);

        ui.horizontal(|ui| {
            if ui
                .add_enabled(!self.busy, egui::Button::new("Repair installation"))
                .clicked()
            {
                self.start("repair");
            }

            if ui
                .add_enabled(!self.busy, egui::Button::new("Uninstall"))
                .clicked()
            {
                self.confirm_uninstall = true;
            }
        });

        if self.confirm_uninstall && !self.busy {
            ui.separator();
            ui.label("Remove DeckPort VPN system components? Saved settings are kept.");

            ui.horizontal(|ui| {
                if ui.button("Confirm uninstall").clicked() {
                    self.start("uninstall");
                }

                if ui.button("Cancel").clicked() {
                    self.confirm_uninstall = false;
                }
            });
        }

        ui.separator();

        egui::ScrollArea::vertical().show(ui, |ui| {
            if self.output.is_empty() {
                ui.label("Setup progress and safe installation messages appear here.");
            } else {
                ui.label(&self.output);
            }
        });
    }
}
fn current_release() -> Result<PathBuf, String> {
    let base = Path::new(BASE);
    let current = base.join("current");

    let info = fs::symlink_metadata(&current)
        .map_err(|_| "DeckPort VPN installation was not found".to_string())?;

    if !info.file_type().is_symlink() {
        return Err("Unsafe DeckPort VPN installation".to_string());
    }

    let releases = base
        .join("releases")
        .canonicalize()
        .map_err(|_| "DeckPort VPN releases directory is missing".to_string())?;

    let release = current
        .canonicalize()
        .map_err(|_| "DeckPort VPN installation is incomplete".to_string())?;

    if release.parent() != Some(releases.as_path()) {
        return Err("Unsafe DeckPort VPN installation".to_string());
    }

    Ok(release)
}

fn repair_files(release: &Path) -> Result<(PathBuf, String), String> {
    let payload = release.join("payload.zip");
    let checksum = release.join("payload.sha256");

    if !payload.is_file() || !checksum.is_file() {
        return Err("The installed repair payload is incomplete".to_string());
    }

    let digest = fs::read_to_string(checksum)
        .map_err(|_| "Could not read the payload checksum".to_string())?
        .trim()
        .to_ascii_lowercase();

    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("The installed payload checksum is invalid".to_string());
    }

    Ok((payload, digest))
}

fn run_installer(action: &str) -> Result<String, String> {
    let release = current_release()?;
    let entry = release.join("installer/entry.py");

    if !entry.is_file() {
        return Err("The installed root installer is missing".to_string());
    }

    let mut command = Command::new("/usr/bin/pkexec");
    command
        .arg("/usr/bin/python3")
        .arg("-B")
        .arg(&entry)
        .arg(action);

    if action == "repair" {
        let (payload, digest) = repair_files(&release)?;

        command
            .arg("--payload")
            .arg(payload)
            .arg("--sha256")
            .arg(digest);
    } else if action != "uninstall" {
        return Err("Unsupported Setup operation".to_string());
    }

    let result = command
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| "Could not start system authorization".to_string())?;

    let stdout = String::from_utf8_lossy(&result.stdout);
    let mut messages = Vec::new();
    let mut completed = false;
    let mut failure = None;

    for line in stdout.lines() {
        let Ok(item) = serde_json::from_str::<Value>(line) else {
            continue;
        };

        if let Some(progress) = item.get("progress").and_then(Value::as_u64) {
            let message = item.get("message").and_then(Value::as_str).unwrap_or("");

            messages.push(format!("{progress}%  {message}"));
        }

        match item.get("ok").and_then(Value::as_bool) {
            Some(true) => completed = true,
            Some(false) => {
                failure = item
                    .get("reason")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
            }
            None => {}
        }
    }

    if result.status.success() && completed {
        if messages.is_empty() {
            Ok("Operation completed successfully.".to_string())
        } else {
            Ok(messages.join("\n"))
        }
    } else {
        Err(failure.unwrap_or_else(|| "Installation operation did not complete".to_string()))
    }
}
