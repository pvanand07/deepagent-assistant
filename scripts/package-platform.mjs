#!/usr/bin/env node
/**
 * Platform-aware packaging entrypoints for package.json scripts.
 * Windows → PowerShell; macOS → bash package-sidecar.sh + tauri --bundles dmg.
 */
import { accessSync, constants } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import { platform } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const action = process.argv[2];

function run(command, args, opts = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: opts.shell ?? false,
    env: process.env,
  });
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function packageSidecar() {
  if (platform() === "win32") {
    run("powershell", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      path.join("scripts", "package-sidecar.ps1"),
    ]);
    return;
  }
  if (platform() === "darwin") {
    run("bash", [path.join("scripts", "package-sidecar.sh")]);
    return;
  }
  console.error(
    `package:sidecar is only defined for Windows and macOS (got ${platform()}).`,
  );
  process.exit(1);
}

function packagePortable() {
  if (platform() !== "win32") {
    console.error("package:portable is Windows-only.");
    process.exit(1);
  }
  run("powershell", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    path.join("scripts", "package-portable.ps1"),
  ]);
}

function buildRelease() {
  packageSidecar();
  if (platform() === "win32") {
    run("pnpm", ["exec", "tauri", "build", "--bundles", "nsis"], { shell: true });
    packagePortable();
    return;
  }
  if (platform() === "darwin") {
    run("pnpm", ["exec", "tauri", "build", "--bundles", "dmg"], { shell: true });
    return;
  }
  console.error(`build:release is only defined for Windows and macOS (got ${platform()}).`);
  process.exit(1);
}

function resolveSidecarPython() {
  if (platform() === "win32") {
    return path.join(root, "sidecar", "python.exe");
  }
  for (const c of [
    path.join(root, "sidecar", "bin", "python3"),
    path.join(root, "sidecar", "bin", "python"),
  ]) {
    try {
      accessSync(c, constants.F_OK);
      return c;
    } catch {
      /* try next */
    }
  }
  return path.join(root, "sidecar", "bin", "python3");
}

async function smokeHealth() {
  const python = resolveSidecarPython();
  const env = {
    ...process.env,
    PYTHONPATH: path.join(root, "sidecar", "src"),
    DEEPAGENT_DESKTOP: "1",
  };

  const importSmoke = spawnSync(
    python,
    ["-c", "from api import app; print('api:app ok')"],
    { cwd: root, stdio: "inherit", env },
  );
  if (importSmoke.status !== 0) process.exit(importSmoke.status ?? 1);

  const port = 18766;
  const child = spawn(
    python,
    ["-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: root, env, stdio: "ignore" },
  );

  const deadline = Date.now() + 15000;
  let ok = false;
  while (Date.now() < deadline) {
    ok = await new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        res.resume();
        resolve(res.statusCode >= 200 && res.statusCode < 300);
      });
      req.on("error", () => resolve(false));
      req.setTimeout(2000, () => {
        req.destroy();
        resolve(false);
      });
    });
    if (ok) break;
    await new Promise((r) => setTimeout(r, 250));
  }

  child.kill("SIGTERM");
  await new Promise((r) => {
    child.on("exit", r);
    setTimeout(r, 5000);
  });

  if (!ok) {
    console.error("uvicorn /health smoke failed");
    process.exit(1);
  }
  console.log("health ok");
}

switch (action) {
  case "sidecar":
    packageSidecar();
    break;
  case "portable":
    packagePortable();
    break;
  case "release":
    buildRelease();
    break;
  case "smoke":
    smokeHealth().catch((err) => {
      console.error(err);
      process.exit(1);
    });
    break;
  default:
    console.error(
      `Usage: node scripts/package-platform.mjs <sidecar|portable|release|smoke>`,
    );
    process.exit(1);
}
