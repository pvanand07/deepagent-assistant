"""Agent-visible Bubblewrap status helper."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from deep_agent.sandbox.manager import get_manager


def build_sandbox_tools() -> list[Any]:
    @tool
    def sandbox_status() -> str:
        """Show whether the shared Bubblewrap sandbox is ready.

        Returns JSON with busy flag, holder session/run ids, workdir, and network.
        """
        return json.dumps(get_manager().status_dict(), indent=2)
    return [sandbox_status]
