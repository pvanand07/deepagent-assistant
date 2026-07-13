//! FastAPI sidecar lifecycle: packaged CPython or dev `uv run`.
//!
//! Packaged release builds spawn bundled Python under `resources/sidecar/`:
//! - Windows: `python.exe -m uvicorn …`
//! - macOS/Linux: `bin/python3` (or `python3` / `bin/python`) `-m uvicorn …`
//!
//! `pnpm tauri dev` (debug) always uses repo root + `uv run` / system Python,
//! even if `target/*/sidecar` exists from a prior package step.
//! See docs/tauri-migration.md Phase 3 and docs/macos-packaging.md.

use std::{
    io::{self, BufRead, BufReader},
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use tauri::{AppHandle, Manager};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

const PREFERRED_PORT: u16 = 8010;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);
const HEALTH_POLL: Duration = Duration::from_millis(250);

#[derive(Clone, Debug)]
pub struct SidecarPaths {
    /// Repo root (dev) or bundled `sidecar/` directory (packaged).
    pub root: PathBuf,
    pub data_dir: PathBuf,
    pub workdir: PathBuf,
    /// Set when bundled Python is present under resources.
    pub python_exe: Option<PathBuf>,
}

impl SidecarPaths {
    fn data_and_workdir(fallback_root: &Path) -> (PathBuf, PathBuf) {
        // dirs::data_dir → Roaming AppData (Windows) / Application Support (macOS)
        let data_dir = dirs::data_dir()
            .unwrap_or_else(|| fallback_root.join("data"))
            .join("DeepAgent");

        // Documents/DeepAgent/workspace
        let workdir = dirs::document_dir()
            .unwrap_or_else(|| fallback_root.join("workspace"))
            .join("DeepAgent")
            .join("workspace");

        (data_dir, workdir)
    }

    /// Dev layout: `CARGO_MANIFEST_DIR` = `<repo>/src-tauri` → parent is repo root.
    pub fn resolve_dev() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("src-tauri parent")
            .to_path_buf();
        let (data_dir, workdir) = Self::data_and_workdir(&root);
        Self {
            root,
            data_dir,
            workdir,
            python_exe: None,
        }
    }

    /// Candidates for packaged Python under `$RESOURCE/sidecar/`.
    fn find_packaged_python(sidecar_root: &Path) -> Option<PathBuf> {
        #[cfg(windows)]
        {
            let python = sidecar_root.join("python.exe");
            if python.is_file() {
                return Some(python);
            }
        }
        #[cfg(not(windows))]
        {
            for rel in ["bin/python3", "bin/python", "python3", "python"] {
                let candidate = sidecar_root.join(rel);
                if candidate.is_file() {
                    return Some(candidate);
                }
            }
        }
        None
    }

    /// Prefer bundled Python under `$RESOURCE/sidecar/`; else dev.
    ///
    /// Debug/`tauri dev` always uses the repo + `uv run` so a leftover
    /// packaged sidecar from a prior package step does not win.
    pub fn resolve_with_app(app: &AppHandle) -> Self {
        if cfg!(debug_assertions) {
            let _ = app;
            return Self::resolve_dev();
        }
        if let Ok(resource_dir) = app.path().resource_dir() {
            let sidecar_root = resource_dir.join("sidecar");
            if let Some(python) = Self::find_packaged_python(&sidecar_root) {
                let (data_dir, workdir) = Self::data_and_workdir(&sidecar_root);
                return Self {
                    root: sidecar_root,
                    data_dir,
                    workdir,
                    python_exe: Some(python),
                };
            }
        }
        Self::resolve_dev()
    }
}

/// Keep reading child stdout/stderr so the OS pipe buffer cannot fill and
/// block uvicorn (which freezes all HTTP handlers).
fn pipe_child_stdio(child: &mut Child) {
    if let Some(stdout) = child.stdout.take() {
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                match line {
                    Ok(line) => eprintln!("[sidecar] {line}"),
                    Err(_) => break,
                }
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                match line {
                    Ok(line) => eprintln!("[sidecar] {line}"),
                    Err(_) => break,
                }
            }
        });
    }
}

/// Kill the sidecar process tree (Windows taskkill /T; Unix process group).
fn kill_sidecar_tree(child: &mut Child) {
    let pid = child.id();
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(unix)]
    {
        // Negative PID = process group (requires process_group(0) at spawn).
        unsafe {
            let _ = libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

pub struct SidecarHandle {
    pub port: u16,
    child: Child,
}

impl SidecarHandle {
    pub fn kill(mut self) {
        // Kill the process tree — `uv run` may leave uvicorn as a grandchild.
        kill_sidecar_tree(&mut self.child);
    }
}

#[derive(Debug)]
pub enum SidecarError {
    Io(io::Error),
    Spawn(String),
    HealthTimeout { port: u16, detail: String },
}

impl std::fmt::Display for SidecarError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(err) => write!(f, "{err}"),
            Self::Spawn(msg) => write!(f, "{msg}"),
            Self::HealthTimeout { port, detail } => {
                write!(
                    f,
                    "Timed out waiting for http://127.0.0.1:{port}/health.\n{detail}"
                )
            }
        }
    }
}

impl From<io::Error> for SidecarError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

/// Bind probe — prefer 8010, else first free ephemeral-ish port in a small range.
pub fn pick_port() -> io::Result<u16> {
    if port_free(PREFERRED_PORT) {
        return Ok(PREFERRED_PORT);
    }
    for port in (PREFERRED_PORT + 1)..=(PREFERRED_PORT + 50) {
        if port_free(port) {
            return Ok(port);
        }
    }
    // Last resort: OS-assigned free port
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn port_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn command_exists(program: &str) -> bool {
    Command::new(program)
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn ensure_dirs(paths: &SidecarPaths) -> io::Result<()> {
    std::fs::create_dir_all(&paths.data_dir)?;
    std::fs::create_dir_all(&paths.workdir)?;
    Ok(())
}

fn apply_sidecar_env(cmd: &mut Command, paths: &SidecarPaths) {
    let pythonpath = paths.root.join("src");
    cmd.current_dir(&paths.root)
        .env("DEEPAGENT_DESKTOP", "1")
        .env("DEEPAGENT_DATA_DIR", &paths.data_dir)
        .env("DEEPAGENT_WORKDIR", &paths.workdir)
        .env("PYTHONPATH", &pythonpath)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
}

/// Put the child in its own process group so quit can SIGKILL the whole tree.
#[cfg(unix)]
fn prepare_unix_process_group(cmd: &mut Command) {
    // 0 → child's PID becomes the new PGID (stable since Rust 1.64).
    cmd.process_group(0);
}

#[cfg(not(unix))]
fn prepare_unix_process_group(_cmd: &mut Command) {}

/// Packaged: bundled Python `-m uvicorn`. Dev: `uv run` / system Python.
fn spawn_uvicorn(paths: &SidecarPaths, port: u16) -> Result<Child, SidecarError> {
    let host = "127.0.0.1";
    let port_s = port.to_string();

    if let Some(python) = &paths.python_exe {
        let mut cmd = Command::new(python);
        cmd.args([
            "-m",
            "uvicorn",
            "deep_agent.api.app:app",
            "--host",
            host,
            "--port",
            &port_s,
        ]);
        apply_sidecar_env(&mut cmd, paths);
        prepare_unix_process_group(&mut cmd);
        return cmd.spawn().map_err(|e| {
            SidecarError::Spawn(format!(
                "failed to spawn packaged `{} -m uvicorn`: {e}",
                python.display()
            ))
        });
    }

    if command_exists("uv") {
        let mut cmd = Command::new("uv");
        cmd.args([
            "run",
            "uvicorn",
            "deep_agent.api.app:app",
            "--host",
            host,
            "--port",
            &port_s,
        ]);
        apply_sidecar_env(&mut cmd, paths);
        prepare_unix_process_group(&mut cmd);
        return cmd.spawn().map_err(|e| {
            SidecarError::Spawn(format!("failed to spawn `uv run uvicorn`: {e}"))
        });
    }

    for program in ["python", "python3", "py"] {
        if !command_exists(program) {
            continue;
        }
        let mut cmd = Command::new(program);
        if program == "py" {
            cmd.arg("-3");
        }
        cmd.args([
            "-m",
            "uvicorn",
            "deep_agent.api.app:app",
            "--host",
            host,
            "--port",
            &port_s,
        ]);
        apply_sidecar_env(&mut cmd, paths);
        prepare_unix_process_group(&mut cmd);
        match cmd.spawn() {
            Ok(child) => return Ok(child),
            Err(e) => {
                return Err(SidecarError::Spawn(format!(
                    "failed to spawn `{program} -m uvicorn`: {e}"
                )));
            }
        }
    }

    Err(SidecarError::Spawn(
        "No packaged sidecar Python and neither `uv` nor `python`/`python3`/`py` found on PATH. \
         Run `pnpm package:sidecar` for release builds, or install uv / Python 3.12+ for dev."
            .into(),
    ))
}

fn health_ok(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/health");
    ureq::get(&url)
        .timeout(Duration::from_secs(2))
        .call()
        .map(|r| r.status() >= 200 && r.status() < 300)
        .unwrap_or(false)
}

fn wait_for_health(port: u16, child: &mut Child) -> Result<(), SidecarError> {
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    while Instant::now() < deadline {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(SidecarError::HealthTimeout {
                port,
                detail: format!("sidecar exited early with status {status}"),
            });
        }
        if health_ok(port) {
            return Ok(());
        }
        thread::sleep(HEALTH_POLL);
    }
    Err(SidecarError::HealthTimeout {
        port,
        detail: format!(
            "No OK response within {}s. Packaged: check resources/sidecar. Dev: PYTHONPATH=src and `uv sync`?",
            HEALTH_TIMEOUT.as_secs()
        ),
    })
}

pub fn spawn_and_wait(paths: &SidecarPaths) -> Result<SidecarHandle, SidecarError> {
    ensure_dirs(paths)?;
    let port = pick_port()?;
    let mut child = spawn_uvicorn(paths, port)?;
    pipe_child_stdio(&mut child);
    match wait_for_health(port, &mut child) {
        Ok(()) => Ok(SidecarHandle { port, child }),
        Err(err) => {
            kill_sidecar_tree(&mut child);
            Err(err)
        }
    }
}
