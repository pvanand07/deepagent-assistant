//! Deep Agent Tauri shell — window, sidecar lifecycle, menu, single-instance.
//!
//! Product UI stays in `frontend/` served by uvicorn. Packaged builds spawn
//! embeddable CPython from resources; `tauri dev` uses `uv run`.
//! See docs/tauri-migration.md.

mod sidecar;

use std::sync::Mutex;

use serde::Serialize;
use sidecar::{SidecarHandle, SidecarPaths};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    Emitter, Manager, RunEvent, WindowEvent,
};
use tauri_plugin_opener::OpenerExt;

#[derive(Clone, Serialize)]
struct StatusPayload {
    message: String,
    error: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
}

struct AppState {
    sidecar: Mutex<Option<SidecarHandle>>,
    paths: Mutex<SidecarPaths>,
}

fn emit_status(app: &tauri::AppHandle, message: impl Into<String>, error: bool, detail: Option<String>) {
    let _ = app.emit(
        "sidecar-status",
        StatusPayload {
            message: message.into(),
            error,
            detail,
        },
    );
}

fn open_folder(app: &tauri::AppHandle, path: &std::path::Path) {
    if let Err(err) = std::fs::create_dir_all(path) {
        eprintln!("failed to create folder {}: {err}", path.display());
        return;
    }
    // opener plugin: open path in the default file manager / Explorer
    // https://v2.tauri.app/plugin/opener/
    if let Err(err) = app.opener().open_path(path.to_string_lossy(), None::<&str>) {
        eprintln!("failed to open {}: {err}", path.display());
    }
}

fn navigate_main(app: &tauri::AppHandle, url: &str) {
    if let Some(window) = app.get_webview_window("main") {
        match url.parse() {
            Ok(parsed) => {
                if let Err(err) = window.navigate(parsed) {
                    eprintln!("navigate failed: {err}");
                }
            }
            Err(err) => eprintln!("invalid url {url}: {err}"),
        }
    }
}

fn build_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let open_workspace =
        MenuItem::with_id(app, "open-workspace", "Open workspace", true, None::<&str>)?;
    #[cfg(target_os = "macos")]
    let open_data_label = "Open Application Support";
    #[cfg(target_os = "windows")]
    let open_data_label = "Open AppData";
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let open_data_label = "Open data folder";
    let open_appdata =
        MenuItem::with_id(app, "open-appdata", open_data_label, true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;

    let app_menu = Submenu::with_items(
        app,
        "Deep Agent",
        true,
        &[&open_workspace, &open_appdata, &settings, &sep, &quit],
    )?;

    Menu::with_items(app, &[&app_menu])
}

fn kill_sidecar(state: &AppState) {
    if let Ok(mut guard) = state.sidecar.lock() {
        if let Some(handle) = guard.take() {
            handle.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(AppState {
            sidecar: Mutex::new(None),
            // Placeholder until setup resolves packaged vs dev paths.
            paths: Mutex::new(SidecarPaths::resolve_dev()),
        });

    // https://v2.tauri.app/plugin/single-instance/
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }));
    }

    builder
        .setup(|app| {
            let menu = build_menu(app.handle())?;
            app.set_menu(menu)?;

            let paths = SidecarPaths::resolve_with_app(app.handle());
            {
                let state = app.state::<AppState>();
                *state.paths.lock().expect("paths mutex") = paths.clone();
            }

            let handle = app.handle().clone();

            // Spawn sidecar off the UI thread; show stub until /health is OK.
            std::thread::spawn(move || {
                let mode = if paths.python_exe.is_some() {
                    "packaged sidecar"
                } else {
                    "dev (uv / python)"
                };
                emit_status(&handle, "Starting Deep Agent…", false, None);
                emit_status(
                    &handle,
                    format!("Starting API ({mode})…"),
                    false,
                    Some(format!(
                        "data: {}\nworkspace: {}\nroot: {}",
                        paths.data_dir.display(),
                        paths.workdir.display(),
                        paths.root.display()
                    )),
                );

                match sidecar::spawn_and_wait(&paths) {
                    Ok(sidecar_handle) => {
                        let port = sidecar_handle.port;
                        let url = format!("http://127.0.0.1:{port}/");
                        {
                            let state = handle.state::<AppState>();
                            let mut guard = state.sidecar.lock().expect("sidecar mutex");
                            *guard = Some(sidecar_handle);
                        }
                        emit_status(&handle, "API ready — opening UI…", false, None);
                        navigate_main(&handle, &url);
                    }
                    Err(err) => {
                        emit_status(
                            &handle,
                            "Failed to start Deep Agent",
                            true,
                            Some(err.to_string()),
                        );
                    }
                }
            });

            Ok(())
        })
        .on_menu_event(|app, event| {
            let state = app.state::<AppState>();
            let paths = state.paths.lock().expect("paths mutex").clone();
            match event.id().as_ref() {
                "quit" => {
                    kill_sidecar(&state);
                    app.exit(0);
                }
                "open-workspace" => open_folder(app, &paths.workdir),
                "open-appdata" => open_folder(app, &paths.data_dir),
                "settings" => {
                    let port = state
                        .sidecar
                        .lock()
                        .ok()
                        .and_then(|g| g.as_ref().map(|h| h.port));
                    if let Some(port) = port {
                        navigate_main(app, &format!("http://127.0.0.1:{port}/#settings"));
                    } else {
                        emit_status(
                            app,
                            "API not ready yet",
                            true,
                            Some("Wait until the sidecar is healthy, then open Settings.".into()),
                        );
                    }
                }
                _ => {}
            }
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                let app = window.app_handle();
                let state = app.state::<AppState>();
                kill_sidecar(&state);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Deep Agent")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                let state = app_handle.state::<AppState>();
                kill_sidecar(&state);
            }
        });
}
