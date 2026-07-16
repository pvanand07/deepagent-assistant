"""Agent tools for shared-sandbox lock status, wait, and cancel."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from deep_agent.sandbox.html_bundle import bundle_html_file
from deep_agent.sandbox.html_tools import inspect_html_file, screenshot_html_file
from deep_agent.sandbox.manager import get_manager


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

    @tool
    def bundle_html(
        input_path: str,
        output_path: str = "",
        overwrite: bool = False,
    ) -> str:
        """Package workspace HTML and its local assets into one HTML file.

        Local stylesheets, scripts, images, icons, fonts, and CSS ``url()``
        assets are inlined. Remote URLs are left unchanged and listed in the
        result. Paths must be relative to /workspace (or start with
        /workspace/). The default output is ``<input-stem>.single.html``.

        Args:
            input_path: Existing .html/.htm file inside /workspace.
            output_path: Optional destination inside /workspace.
            overwrite: Permit replacing an existing destination. Defaults false.
        """
        try:
            result = bundle_html_file(
                get_manager().workdir,
                input_path,
                output_path or None,
                overwrite=overwrite,
            )
        except (FileExistsError, FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
        return json.dumps(result, indent=2)

    @tool
    async def inspect_html(
        input_path: str,
        viewport_width: int = 1440,
        viewport_height: int = 900,
        virtual_time_budget_ms: int = 2000,
        max_text_chars: int = 12000,
    ) -> str:
        """Render workspace HTML in Chromium and inspect the resulting page.

        Returns title, rendered text, headings, links, forms, images, missing
        image alt attributes, resource URLs, tag counts, and browser errors.
        Only local .html/.htm files inside /workspace are accepted.
        """
        try:
            result = await inspect_html_file(
                get_manager(),
                input_path,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                virtual_time_budget_ms=virtual_time_budget_ms,
                max_text_chars=max_text_chars,
            )
        except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
        return json.dumps(result, indent=2)

    @tool
    async def screenshot_html(
        input_path: str,
        output_path: str = "",
        viewport_width: int = 1440,
        viewport_height: int = 900,
        virtual_time_budget_ms: int = 2000,
        overwrite: bool = False,
    ) -> str:
        """Render workspace HTML in Chromium and save a PNG viewport screenshot.

        Only local .html/.htm input and .png output paths inside /workspace are
        accepted. The default output is a unique file under
        /workspace/.deepagent/previews/.
        """
        try:
            result = await screenshot_html_file(
                get_manager(),
                input_path,
                output_path or None,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                virtual_time_budget_ms=virtual_time_budget_ms,
                overwrite=overwrite,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
        return json.dumps(result, indent=2)

    return [
        sandbox_status,
        sandbox_wait,
        cancel_sandbox_holder,
        bundle_html,
        inspect_html,
        screenshot_html,
    ]
