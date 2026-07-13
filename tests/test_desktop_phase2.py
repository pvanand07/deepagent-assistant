"""Unit tests for desktop path / env / agents / degraded sandbox status."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from agent import ensure_agents_copied, resolve_agents_dir
from sandbox_config import (
    default_workdir,
    env_dir,
    is_desktop_mode,
    load_app_env,
    read_settings_env,
    resolve_data_dir,
    write_settings_env,
)
from sandbox_manager import SandboxManager, get_manager, reset_manager_for_tests
from session_persistence import default_data_dir


def test_resolve_data_dir_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = tmp_path / "custom-data"
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.delenv("DEEPAGENT_DESKTOP", raising=False)
    assert resolve_data_dir() == data.resolve()
    assert default_data_dir() == data.resolve()


def test_resolve_data_dir_desktop_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("DEEPAGENT_DESKTOP", "1")
    monkeypatch.delenv("DEEPAGENT_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    assert resolve_data_dir() == (appdata / "DeepAgent").resolve()
    assert is_desktop_mode() is True


def test_default_workdir_desktop_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPAGENT_DESKTOP", "1")
    monkeypatch.delenv("DEEPAGENT_WORKDIR", raising=False)
    monkeypatch.delenv("CODEX_GUI_WORKSPACE", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("sandbox_config.Path.home", staticmethod(lambda: home))
    expected = (home / "Documents" / "DeepAgent" / "workspace").resolve()
    assert default_workdir() == expected


def test_load_app_env_from_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("OPENROUTER_MODEL=from-data-dir\n", encoding="utf-8")
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.delenv("DEEPAGENT_DESKTOP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    root = load_app_env()
    assert root == data.resolve()
    assert env_dir() == data.resolve()
    assert __import__("os").environ.get("OPENROUTER_MODEL") == "from-data-dir"


def test_write_and_read_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-old-secret-key-1234")
    write_settings_env(
        {
            "OPENROUTER_API_KEY": "sk-new-secret-key-9999",
            "OPENROUTER_MODEL": "openai/gpt-5",
            "DEEPAGENT_NETWORK_ACCESS": "true",
            "DEEPAGENT_SANDBOX_MEMORY": "2048",
            "DEEPAGENT_DNS_NAMESERVERS": "1.1.1.1,8.8.8.8",
        }
    )
    env_text = (data / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_MODEL=openai/gpt-5" in env_text
    assert "sk-new-secret-key-9999" in env_text
    assert "DEEPAGENT_NETWORK_ACCESS=true" in env_text
    assert "DEEPAGENT_SANDBOX_MEMORY=2048" in env_text
    values = read_settings_env()
    assert values["OPENROUTER_MODEL"] == "openai/gpt-5"
    assert values["OPENROUTER_API_KEY_set"] == "true"
    assert "9999" in values["OPENROUTER_API_KEY"]
    assert "sk-new-secret" not in values["OPENROUTER_API_KEY"]
    assert values["DEEPAGENT_NETWORK_ACCESS"] == "true"
    assert values["DEEPAGENT_SANDBOX_MEMORY"] == "2048"


def test_write_settings_network_false_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    write_settings_env({"DEEPAGENT_NETWORK_ACCESS": "false"})
    env_text = (data / ".env").read_text(encoding="utf-8")
    assert "DEEPAGENT_NETWORK_ACCESS=false" in env_text
    assert __import__("os").environ.get("DEEPAGENT_NETWORK_ACCESS") == "false"


def test_agents_first_run_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.setenv("DEEPAGENT_DESKTOP", "1")
    dest = ensure_agents_copied()
    assert dest == data / "agents"
    toml_files = list(dest.glob("*.toml"))
    assert toml_files, "expected default agent TOML files to be copied"
    # Second call should not fail / wipe
    ensure_agents_copied()
    assert resolve_agents_dir() == dest


def test_mcp_config_prefers_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_tools import _config_paths

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.delenv("DEEPAGENT_MCP_CONFIG", raising=False)
    paths = _config_paths()
    assert paths[0] == data.resolve() / ".mcp.json"


@pytest.mark.asyncio
async def test_degraded_sandbox_startup_and_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reset_manager_for_tests()
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path / "workspace"))
    monkeypatch.delenv("DEEPAGENT_SANDBOX_BACKEND", raising=False)

    manager = SandboxManager()

    async def fail_create() -> None:
        raise RuntimeError("WHP missing")

    async def fake_startup() -> None:
        # Mirror real startup's degraded path without depending on microsandbox.
        manager._loop = __import__("asyncio").get_running_loop()
        manager._workdir = default_workdir()
        manager._workdir.mkdir(parents=True, exist_ok=True)
        try:
            await fail_create()
        except Exception as exc:
            manager._enter_degraded(f"microsandbox could not create a microVM: {exc}")

    await fake_startup()

    assert manager.started is True
    assert manager.healthy is False
    assert manager.degraded is True
    assert manager.backend is None
    status = manager.status_dict()
    assert status["degraded"] is True
    assert status["backend"] == "unavailable"
    assert "WHP" in (status["fix_it"] or "")
    assert "WHP missing" in (status["degraded_reason"] or "")
    reset_manager_for_tests()


@pytest.mark.asyncio
async def test_startup_degrades_when_create_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reset_manager_for_tests()
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "microsandbox")

    manager = get_manager()
    with patch.object(
        manager, "_create_sandbox", new=AsyncMock(side_effect=RuntimeError("no WHP"))
    ):
        # Make install check a no-op by degrading on import failure or create failure.
        try:
            import microsandbox as msb

            monkeypatch.setattr(msb, "is_installed", lambda: True)

            async def _noop_install() -> None:
                return None

            monkeypatch.setattr(msb, "install", _noop_install)
        except ImportError:
            pass
        await manager.startup()

    assert manager.started is True
    assert manager.degraded is True
    assert manager.backend is None
    reset_manager_for_tests()



@pytest.mark.asyncio
async def test_health_and_config_report_degraded(
    client: AsyncClient,
) -> None:
    manager = get_manager()
    manager._healthy = False
    manager._degraded_reason = "test degraded"
    manager._fix_it = "enable WHP"
    manager._started = True
    manager._backend = None

    health = await client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "degraded"
    assert body["sandbox_degraded"] is True
    assert body["sandbox_status"]["degraded_reason"] == "test degraded"

    cfg = await client.get("/api/config")
    assert cfg.status_code == 200
    assert cfg.json()["sandbox_degraded"] is True


@pytest.mark.asyncio
async def test_settings_api_roundtrip(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    get_resp = await client.get("/api/settings")
    assert get_resp.status_code == 200
    assert get_resp.json()["data_dir"] == str(data_dir.resolve())

    put = await client.put(
        "/api/settings",
        json={"values": {"OPENROUTER_MODEL": "test/model-phase2"}},
    )
    assert put.status_code == 200
    assert put.json()["values"]["OPENROUTER_MODEL"] == "test/model-phase2"
    assert put.json()["sandbox_recreated"] is False
    env_file = data_dir / ".env"
    assert env_file.is_file()
    assert "OPENROUTER_MODEL=test/model-phase2" in env_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_settings_api_persists_network_and_recreates_stub(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    monkeypatch.delenv("DEEPAGENT_NETWORK_ACCESS", raising=False)

    mgr = get_manager()
    assert mgr.started
    assert mgr.network is False

    put = await client.put(
        "/api/settings",
        json={
            "values": {
                "DEEPAGENT_NETWORK_ACCESS": "true",
                "DEEPAGENT_SANDBOX_MEMORY": "1536",
                "DEEPAGENT_EXEC_TIMEOUT": "90",
            }
        },
    )
    assert put.status_code == 200
    body = put.json()
    assert body["sandbox_recreated"] is True
    assert body["values"]["DEEPAGENT_NETWORK_ACCESS"] == "true"
    assert body["values"]["DEEPAGENT_SANDBOX_MEMORY"] == "1536"
    assert body["values"]["DEEPAGENT_EXEC_TIMEOUT"] == "90"
    assert body["sandbox_status"]["network"] is True

    env_text = (data_dir / ".env").read_text(encoding="utf-8")
    assert "DEEPAGENT_NETWORK_ACCESS=true" in env_text
    assert "DEEPAGENT_SANDBOX_MEMORY=1536" in env_text

    cfg = await client.get("/api/config")
    assert cfg.status_code == 200
    assert cfg.json()["default_network"] is True
    assert cfg.json()["sandbox_status"]["network"] is True
    assert get_manager().network is True

    # Same fingerprint → no recreate; exec timeout alone does not recreate.
    put2 = await client.put(
        "/api/settings",
        json={"values": {"DEEPAGENT_NETWORK_ACCESS": "true", "DEEPAGENT_EXEC_TIMEOUT": "60"}},
    )
    assert put2.status_code == 200
    assert put2.json()["sandbox_recreated"] is False
    assert put2.json()["values"]["DEEPAGENT_EXEC_TIMEOUT"] == "60"
