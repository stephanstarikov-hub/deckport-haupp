mod app;
mod ipc;
mod setup;
mod theme;

use eframe::egui;
use serde_json::{Value, json};

fn run_cli_action(argument: &str) -> Result<bool, String> {
    match argument {
        "--version" => {
            println!("DeckPort VPN {}", env!("DECKPORT_VERSION"));
            Ok(true)
        }
        "--connect" => {
            let status = ipc::call("status", vec![])?;
            let selected = status
                .get("selected")
                .and_then(Value::as_str)
                .ok_or_else(|| "No VPN server is selected".to_string())?
                .to_owned();

            ipc::call("connect", vec![json!(selected)])?;
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
            .with_inner_size([1280.0, 760.0])
            .with_min_inner_size([800.0, 560.0]),
        ..Default::default()
    };

    eframe::run_native(
        "DeckPort VPN",
        options,
        Box::new(move |context| {
            theme::apply(&context.egui_ctx);
            let application = if setup_mode {
                app::DeckPortApp::new_setup()
            } else {
                app::DeckPortApp::new()
            };

            Ok(Box::new(application))
        }),
    )
}
