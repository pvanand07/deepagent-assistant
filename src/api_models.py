"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    sandbox_healthy: bool = True
    sandbox_degraded: bool = False
    sandbox_status: dict[str, Any] | None = None


class SettingsResponse(BaseModel):
    desktop: bool = False
    data_dir: str
    workdir: str
    env_path: str
    values: dict[str, str] = Field(default_factory=dict)
    sandbox_recreated: bool = False
    sandbox_status: dict[str, Any] | None = None


class SettingsUpdateRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class ConfigResponse(BaseModel):
    default_model: str
    default_workdir: str | None
    default_network: bool
    mcp_enabled: bool
    mcp_servers: list[str] = Field(default_factory=list)
    username: str
    sandbox_backend: str
    desktop: bool
    data_dir: str
    sandbox_healthy: bool
    sandbox_degraded: bool
    sandbox_status: dict[str, Any] | None = None
    llm_provider: str
    has_api_key: bool


class CreateSessionRequest(BaseModel):
    model: str | None = None
    with_subagents: bool = True
    # Deprecated: ignored. Network/workdir are app-wide via env.
    network: bool | None = None
    workdir: str | None = None


class SessionResponse(BaseModel):
    id: str
    sandbox_id: str
    workdir: str
    network: bool
    model: str
    message_count: int
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_tool_names: list[str] = Field(default_factory=list)
    subagent_names: list[str] = Field(default_factory=list)
    active_run_id: str | None = None
    last_usage: dict[str, Any] | None = None
    last_step_usage: dict[str, Any] | None = None


class SessionSummary(BaseModel):
    id: str
    title: str
    preview: str
    message_count: int
    model: str
    updated_at: float
    active_run_id: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    pwd: str | None = Field(
        None,
        description="Workspace-relative folder path to use as working directory for this turn",
    )


class RunResponse(BaseModel):
    """Returned by POST /chat (202): the turn now executes as a background run.

    Stream it via GET /sessions/{session_id}/runs/{run_id}/events (SSE).
    """

    run_id: str
    session_id: str
    status: str


class ActiveRunResponse(BaseModel):
    run_id: str | None = None


class CancelResponse(BaseModel):
    cancelled: bool


class ResetResponse(BaseModel):
    message_count: int = 0


class MessagesResponse(BaseModel):
    messages: list[dict[str, Any]]


class FileEntry(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int | None = None


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry]


class FileContentResponse(BaseModel):
    path: str
    content: str
    size: int


class FolderListResponse(BaseModel):
    folders: list[str]


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1)
    parent: str = Field("", description="Parent folder path relative to workspace root")


class FolderCreateResponse(BaseModel):
    path: str
