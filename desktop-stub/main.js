// Stub chrome only — product UI is served by the FastAPI sidecar.
// Rust emits status updates while spawning / health-checking the API.

const statusEl = document.getElementById("status");
const detailEl = document.getElementById("detail");

function setStatus(message, isError = false, detail = "") {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  if (detail) {
    detailEl.hidden = false;
    detailEl.textContent = detail;
  } else {
    detailEl.hidden = true;
    detailEl.textContent = "";
  }
}

async function listen() {
  try {
    const { listen } = window.__TAURI__.event;
    await listen("sidecar-status", (event) => {
      const payload = event.payload ?? {};
      setStatus(
        payload.message ?? "Starting Deep Agent…",
        Boolean(payload.error),
        payload.detail ?? ""
      );
    });
  } catch {
    // Not running inside Tauri (opened as a static file) — leave default text.
  }
}

listen();
