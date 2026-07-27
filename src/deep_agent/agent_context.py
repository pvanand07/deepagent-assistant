"""Inject per-turn working directory (pwd) into the agent system prompt.

Uses LangGraph run ``context`` (``agent.stream(..., context={"pwd": ...})``)
so pwd never enters conversation history. A middleware appends the pwd block
to the assembled system message at model-call time, matching how deepagents
injects memory and skills.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ContextT, ModelRequest, ModelResponse, ResponseT
from deepagents.middleware._utils import append_to_system_message


class AgentContext(TypedDict, total=False):
    """Run-scoped context passed to the agent graph."""

    pwd: str


PWD_SYSTEM_PROMPT = """Working directory for this turn:
- Selected pwd: {path}
- Treat this as the active project folder; create and edit files here unless the user directs otherwise.
- Read AGENT.md or AGENTS.md in this folder if present and follow its guidance for work in this pwd."""

PWD_ROOT_SYSTEM_PROMPT = """Working directory for this turn:
- Selected pwd: {path}
- You are at the workspace root. List the directory first, then create a clearly named new folder for this task and save all work there (do not write loose files at /workspace).
- Read /workspace/AGENT.md or AGENTS.md if present and follow its guidance."""


def format_pwd_path(pwd: str | None) -> str:
    clean = (pwd or "").strip().strip("/")
    if not clean or clean == "workspace":
        return "/workspace"
    return f"/workspace/{clean}"


def is_workspace_root(pwd: str | None) -> bool:
    return format_pwd_path(pwd) == "/workspace"


def _pwd_from_context(context: object) -> str | None:
    if context is None:
        return None
    pwd = context.get("pwd") if isinstance(context, dict) else getattr(context, "pwd", None)
    if pwd is None or not str(pwd).strip():
        return None
    return str(pwd).strip()


class PwdContextMiddleware(AgentMiddleware):
    """Append the selected workspace pwd to the system prompt for each model call."""

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        pwd = _pwd_from_context(request.runtime.context)
        path = format_pwd_path(pwd)
        template = PWD_ROOT_SYSTEM_PROMPT if is_workspace_root(pwd) else PWD_SYSTEM_PROMPT
        section = template.format(path=path)
        new_system_message = append_to_system_message(request.system_message, section)
        if new_system_message is request.system_message:
            return request
        return request.override(system_message=new_system_message)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT]:
        return await handler(self.modify_request(request))
