//! In-app auto-updater: check / snooze / install (packaged release builds only).

use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::UpdaterExt;

const SNOOZE_FILENAME: &str = "updater-snooze.json";
const SNOOZE_SECS: u64 = 7 * 24 * 60 * 60;
const LAUNCH_CHECK_DELAY_MS: u64 = 4_000;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub available: bool,
    pub version: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SnoozeState {
    version: String,
    until: u64,
}

fn data_dir() -> PathBuf {
    dirs::data_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("DeepAgent")
}

fn snooze_path() -> PathBuf {
    data_dir().join(SNOOZE_FILENAME)
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn is_snoozed(version: &str) -> bool {
    let path = snooze_path();
    let Ok(raw) = fs::read_to_string(&path) else {
        return false;
    };
    let Ok(state) = serde_json::from_str::<SnoozeState>(&raw) else {
        return false;
    };
    state.version == version && state.until > now_unix()
}

pub fn write_snooze(version: &str) -> Result<(), String> {
    let dir = data_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("create data dir: {e}"))?;
    let state = SnoozeState {
        version: version.to_string(),
        until: now_unix().saturating_add(SNOOZE_SECS),
    };
    let raw = serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?;
    fs::write(snooze_path(), raw).map_err(|e| format!("write snooze: {e}"))
}

/// True in `tauri dev` / debug builds — updater stays off.
pub fn updater_disabled() -> bool {
    cfg!(debug_assertions)
}

#[tauri::command]
pub fn get_app_version(app: AppHandle) -> String {
    app.package_info().version.to_string()
}

#[tauri::command]
pub async fn updater_check(app: AppHandle) -> Result<Option<UpdateInfo>, String> {
    if updater_disabled() {
        return Ok(None);
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;

    match update {
        Some(u) => Ok(Some(UpdateInfo {
            available: true,
            version: u.version,
        })),
        None => Ok(None),
    }
}

#[tauri::command]
pub async fn updater_snooze(version: String) -> Result<(), String> {
    if updater_disabled() {
        return Ok(());
    }
    if version.trim().is_empty() {
        return Err("version is required".into());
    }
    write_snooze(version.trim())
}

#[tauri::command]
pub async fn updater_install(app: AppHandle) -> Result<(), String> {
    if updater_disabled() {
        return Err("Updater is disabled in development builds".into());
    }

    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "No update available".to_string())?;

    // Stop Python sidecar before replacing the app bundle.
    if let Some(state) = app.try_state::<crate::AppState>() {
        crate::kill_sidecar(&state);
    }

    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| e.to_string())?;

    app.restart();
}

/// Quiet launch check: emit `update-available` when a newer version is not snoozed.
pub fn spawn_launch_check(app: AppHandle) {
    if updater_disabled() {
        return;
    }
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(LAUNCH_CHECK_DELAY_MS));
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let Ok(updater) = app.updater() else {
                return;
            };
            let Ok(Some(update)) = updater.check().await else {
                return;
            };
            if is_snoozed(&update.version) {
                return;
            }
            let _ = app.emit(
                "update-available",
                UpdateInfo {
                    available: true,
                    version: update.version,
                },
            );
        });
    });
}
