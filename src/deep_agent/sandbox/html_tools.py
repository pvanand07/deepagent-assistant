"""Rendered HTML inspection and screenshot helpers for the shared sandbox."""

from __future__ import annotations

import re
import shlex
import uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from deep_agent.sandbox.html_bundle import resolve_workspace_path

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ERROR_RE = re.compile(
    r"CONSOLE|Failed to load resource|ERR_|Uncaught|SyntaxError|ReferenceError|TypeError",
    re.IGNORECASE,
)


async def inspect_html_file(
    manager: Any,
    input_path: str,
    *,
    viewport_width: int = 1440,
    viewport_height: int = 900,
    virtual_time_budget_ms: int = 2000,
    max_text_chars: int = 12000,
) -> dict[str, object]:
    """Render workspace HTML with Chromium and return a bounded structural report."""
    source = _validated_html(manager.workdir, input_path)
    width, height = _viewport(viewport_width, viewport_height)
    budget = max(0, min(int(virtual_time_budget_ms), 10000))
    text_limit = max(1000, min(int(max_text_chars), 50000))

    temp_dir = manager.workdir / ".deepagent" / "html-inspect"
    temp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    dom_path = temp_dir / f"{token}.dom.html"
    errors_path = temp_dir / f"{token}.stderr.log"
    guest_dom = _guest_path(manager.workdir, dom_path)
    guest_errors = _guest_path(manager.workdir, errors_path)
    uri = _file_uri(manager.workdir, source)
    command = " ".join(
        [
            "chromium",
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={budget}",
            "--enable-logging=stderr",
            "--dump-dom",
            shlex.quote(uri),
            ">",
            shlex.quote(guest_dom),
            "2>",
            shlex.quote(guest_errors),
        ]
    )

    execution = await manager.exec_command(command, timeout=30)
    try:
        if not dom_path.is_file():
            return {
                "ok": False,
                "error": "Chromium did not produce rendered DOM",
                "chromium_exit_code": execution.response.exit_code,
                "details": execution.response.output[-2000:],
            }
        dom = dom_path.read_text(encoding="utf-8", errors="replace")
        stderr = (
            errors_path.read_text(encoding="utf-8", errors="replace")
            if errors_path.is_file()
            else ""
        )
    finally:
        dom_path.unlink(missing_ok=True)
        errors_path.unlink(missing_ok=True)

    parser = _InspectionParser()
    parser.feed(dom)
    parser.close()
    report = parser.report(text_limit)
    report.update(
        {
            "ok": execution.response.exit_code in (0, None),
            "input_path": _guest_path(manager.workdir, source),
            "viewport": {"width": width, "height": height},
            "rendered_dom_bytes": len(dom.encode("utf-8")),
            "browser_errors": [
                line.strip()
                for line in stderr.splitlines()
                if _ERROR_RE.search(line)
            ][:50],
            "chromium_exit_code": execution.response.exit_code,
        }
    )
    return report


async def screenshot_html_file(
    manager: Any,
    input_path: str,
    output_path: str | None = None,
    *,
    viewport_width: int = 1440,
    viewport_height: int = 900,
    virtual_time_budget_ms: int = 2000,
    overwrite: bool = False,
) -> dict[str, object]:
    """Render workspace HTML with Chromium and persist a PNG viewport capture."""
    source = _validated_html(manager.workdir, input_path)
    width, height = _viewport(viewport_width, viewport_height)
    budget = max(0, min(int(virtual_time_budget_ms), 10000))
    if output_path:
        destination = resolve_workspace_path(manager.workdir, output_path)
    else:
        destination = (
            manager.workdir
            / ".deepagent"
            / "previews"
            / f"{source.stem}-{uuid.uuid4().hex[:8]}.png"
        )
    if destination is None:
        raise ValueError("output_path must stay within /workspace")
    if destination.suffix.lower() != ".png":
        raise ValueError("output_path must end in .png")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {_guest_path(manager.workdir, destination)}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    guest_output = _guest_path(manager.workdir, destination)
    uri = _file_uri(manager.workdir, source)
    command = " ".join(
        [
            "chromium",
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={budget}",
            f"--screenshot={shlex.quote(guest_output)}",
            shlex.quote(uri),
        ]
    )
    execution = await manager.exec_command(command, timeout=30)
    if not destination.is_file():
        return {
            "ok": False,
            "error": "Chromium did not produce a screenshot",
            "chromium_exit_code": execution.response.exit_code,
            "details": execution.response.output[-2000:],
        }
    if not destination.read_bytes().startswith(_PNG_SIGNATURE):
        destination.unlink(missing_ok=True)
        return {"ok": False, "error": "Chromium output is not a valid PNG"}
    return {
        "ok": execution.response.exit_code in (0, None),
        "input_path": _guest_path(manager.workdir, source),
        "output_path": guest_output,
        "bytes": destination.stat().st_size,
        "viewport": {"width": width, "height": height},
        "chromium_exit_code": execution.response.exit_code,
    }


class _InspectionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: Counter[str] = Counter()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.forms: list[dict[str, object]] = []
        self.headings: list[dict[str, str]] = []
        self.resources: set[str] = set()
        self._title_depth = 0
        self._ignored_depth = 0
        self._heading: str | None = None
        self._heading_parts: list[str] = []
        self._form_stack: list[int] = []
        self._link_stack: list[int] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        name = tag.lower()
        values = dict(attrs)
        self.tags[name] += 1
        if name == "title":
            self._title_depth += 1
        if name in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = name
            self._heading_parts = []
        if name == "a" and values.get("href") and len(self.links) < 100:
            self.links.append(
                {"href": values["href"] or "", "text": values.get("aria-label") or ""}
            )
            self._link_stack.append(len(self.links) - 1)
        if name == "img":
            self.images.append(
                {
                    "src": values.get("src"),
                    "alt": values.get("alt"),
                }
            )
        if name == "form":
            self.forms.append(
                {
                    "action": values.get("action") or "",
                    "method": (values.get("method") or "get").lower(),
                    "inputs": 0,
                }
            )
            self._form_stack.append(len(self.forms) - 1)
        elif name in {"input", "select", "textarea", "button"} and self._form_stack:
            form = self.forms[self._form_stack[-1]]
            form["inputs"] = int(form["inputs"]) + 1
        self._record_resource(name, values)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title" and self._title_depth:
            self._title_depth -= 1
        if name in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._heading == name:
            text = _clean_text(" ".join(self._heading_parts))
            if text:
                self.headings.append({"level": name, "text": text})
            self._heading = None
            self._heading_parts = []
        if name == "form" and self._form_stack:
            self._form_stack.pop()
        if name == "a" and self._link_stack:
            self._link_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._heading:
            self._heading_parts.append(data)
        if not self._ignored_depth:
            cleaned = _clean_text(data)
            if cleaned:
                self.text_parts.append(cleaned)
                if self._link_stack:
                    link = self.links[self._link_stack[-1]]
                    link["text"] = _clean_text(f"{link['text']} {cleaned}")

    def report(self, max_text_chars: int) -> dict[str, object]:
        text = _clean_text(" ".join(self.text_parts))
        missing_alt = [
            image.get("src") or ""
            for image in self.images
            if image.get("alt") is None
        ]
        return {
            "title": _clean_text(" ".join(self.title_parts)),
            "rendered_text": text[:max_text_chars],
            "rendered_text_truncated": len(text) > max_text_chars,
            "tag_counts": dict(sorted(self.tags.items())),
            "headings": self.headings[:100],
            "links": self.links,
            "images": self.images[:100],
            "missing_image_alt": missing_alt[:100],
            "forms": self.forms[:50],
            "resource_urls": sorted(self.resources)[:200],
        }

    def _record_resource(self, tag: str, attrs: dict[str, str | None]) -> None:
        candidates: list[str | None] = []
        if tag in {"script", "img", "source", "audio"}:
            candidates.append(attrs.get("src"))
        elif tag == "video":
            candidates.extend((attrs.get("src"), attrs.get("poster")))
        elif tag == "link":
            rel = (attrs.get("rel") or "").lower().split()
            if any(item in rel for item in ("stylesheet", "icon", "apple-touch-icon")):
                candidates.append(attrs.get("href"))
        for value in candidates:
            if value and urlsplit(value).scheme != "data":
                self.resources.add(value)


def _validated_html(workdir: Path, input_path: str) -> Path:
    source = resolve_workspace_path(workdir, input_path)
    if source is None:
        raise ValueError("input_path must stay within /workspace")
    if source.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("input_path must be an .html or .htm file")
    if not source.is_file():
        raise FileNotFoundError(f"HTML input not found: {input_path}")
    return source


def _viewport(width: int, height: int) -> tuple[int, int]:
    return max(320, min(int(width), 3840)), max(240, min(int(height), 2160))


def _file_uri(workdir: Path, source: Path) -> str:
    relative = source.resolve().relative_to(workdir.resolve()).as_posix()
    return f"file:///workspace/{relative}"


def _guest_path(workdir: Path, path: Path) -> str:
    relative = path.resolve().relative_to(workdir.resolve()).as_posix()
    return f"/workspace/{relative}"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
