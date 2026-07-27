"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class CreateSessionRequest(BaseModel):
    model: str | None = None
    network: bool | None = None
    workdir: str | None = None
    with_subagents: bool = True


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


class SessionSummary(BaseModel):
    id: str
    title: str
    preview: str
    message_count: int
    model: str
    updated_at: float


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    pwd: str | None = Field(
        None,
        description="Workspace-relative folder path to use as working directory for this turn",
    )


class ChatResponse(BaseModel):
    reply: str
    messages: list[dict[str, Any]]


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
