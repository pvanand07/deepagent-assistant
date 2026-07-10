"""Agent tools for shared-sandbox lock status, wait, and cancel."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from sandbox_manager import get_manager


def build_sandbox_tools() -> list[Any]:
    @tool
    def sandbox_status() -> str:
        """Show whether the shared microsandbox exec lock is free or held.

        Returns JSON with busy flag, holder session/run ids, workdir, and network.
        Prefer waiting over cancelling when the sandbox is busy.
        """
        return json.dumps(get_manager().status_dict(), indent=2)

    @tool
    async def sandbox_wait(wait_seconds: int = 120) -> str:
        """Wait for the shared sandbox exec lock to become free.

        Args:
            wait_seconds: How long to wait (agent-configurable). Default 120.
                Use 0 to poll once without waiting.

        Prefer this over cancel_sandbox_holder. Only cancel after asking the user.
        """
        result = await get_manager().wait_for_lock(wait_seconds)
        return json.dumps(result, indent=2)

    @tool
    async def cancel_sandbox_holder() -> str:
        """Cancel the chat run that currently holds the sandbox exec lock.

        IMPORTANT: Ask the user for confirmation before calling this. Waiting
        with sandbox_wait is the default. Cancelling another chat's run discards
        that turn's in-flight work.
        """
        result = await get_manager().cancel_holder()
        return json.dumps(result, indent=2)

    return [sandbox_status, sandbox_wait, cancel_sandbox_holder]
