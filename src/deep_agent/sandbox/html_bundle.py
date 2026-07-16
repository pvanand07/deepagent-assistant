"""Bundle workspace HTML and its local assets into one portable file."""

from __future__ import annotations

import base64
import mimetypes
import re
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from deep_agent.sandbox.paths import resolve_under_workdir

_ATTR_RE_TEMPLATE = r"""\b{attr}\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)"""
_REMOTE_SCHEMES = {"http", "https", "blob"}
_EMBEDDED_SCHEMES = {"data", "mailto", "tel", "javascript"}


def bundle_html_file(
    workdir: Path,
    input_path: str,
    output_path: str | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Inline local CSS, JavaScript, and binary assets referenced by an HTML file."""
    source = resolve_workspace_path(workdir, input_path)
    if source is None:
        raise ValueError("input_path must stay within /workspace")
    if source.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("input_path must be an .html or .htm file")
    if not source.is_file():
        raise FileNotFoundError(f"HTML input not found: {input_path}")

    if output_path:
        destination = resolve_workspace_path(workdir, output_path)
    else:
        destination = source.with_name(f"{source.stem}.single.html")
    if destination is None:
        raise ValueError("output_path must stay within /workspace")
    if destination.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("output_path must be an .html or .htm file")
    if destination == source and not overwrite:
        raise FileExistsError("refusing to overwrite input_path; choose another output_path")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {_guest_path(workdir, destination)}")

    state = _BundleState(workdir=workdir.resolve(), html_dir=source.parent)
    html = source.read_text(encoding="utf-8")
    html = _inline_stylesheets(html, state)
    html = _inline_scripts(html, state)
    html = _inline_html_assets(html, state)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    missing_warnings = [
        warning
        for warning in state.warnings
        if "not found" in warning.lower() or "escapes workspace" in warning.lower()
    ]
    return {
        "ok": not missing_warnings,
        "input_path": _guest_path(workdir, source),
        "output_path": _guest_path(workdir, destination),
        "bytes": destination.stat().st_size,
        "inlined": state.inlined,
        "external_dependencies": sorted(state.external),
        "warnings": state.warnings,
    }


class _BundleState:
    def __init__(self, *, workdir: Path, html_dir: Path) -> None:
        self.workdir = workdir
        self.html_dir = html_dir
        self.inlined = {"stylesheets": 0, "scripts": 0, "assets": 0}
        self.external: set[str] = set()
        self.warnings: list[str] = []

    def resolve_asset(self, raw_url: str, base_dir: Path) -> Path | None:
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() in _REMOTE_SCHEMES or parsed.netloc:
            self.external.add(raw_url)
            return None
        if parsed.scheme.lower() in _EMBEDDED_SCHEMES:
            return None
        if raw_url.startswith("#") or not parsed.path:
            return None
        decoded = unquote(parsed.path)
        if decoded.startswith("/"):
            candidate = resolve_under_workdir(self.workdir, decoded.removeprefix("/workspace/"))
        else:
            candidate = (base_dir / decoded).resolve()
            try:
                candidate.relative_to(self.workdir)
            except ValueError:
                candidate = None
        if candidate is None:
            self.warnings.append(f"asset escapes workspace: {raw_url}")
            return None
        return candidate


def _inline_stylesheets(html: str, state: _BundleState) -> str:
    link_re = re.compile(r"<link\b[^>]*>", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        rel = _get_attr(tag, "rel")
        href = _get_attr(tag, "href")
        if not href or not rel or "stylesheet" not in rel.lower().split():
            return tag
        asset = state.resolve_asset(href, state.html_dir)
        if asset is None:
            return tag
        if not asset.is_file():
            state.warnings.append(f"stylesheet not found: {href}")
            return tag
        css = asset.read_text(encoding="utf-8")
        css = _inline_css_urls(css, asset.parent, state)
        state.inlined["stylesheets"] += 1
        return (
            f'<style data-bundled-from="{escape(href, quote=True)}">\n'
            f"{css}\n</style>"
        )

    return link_re.sub(replace, html)


def _inline_scripts(html: str, state: _BundleState) -> str:
    script_re = re.compile(r"<script\b(?P<attrs>[^>]*)>\s*</script\s*>", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        src = _get_attr(attrs, "src")
        if not src:
            return match.group(0)
        asset = state.resolve_asset(src, state.html_dir)
        if asset is None:
            return match.group(0)
        if not asset.is_file():
            state.warnings.append(f"script not found: {src}")
            return match.group(0)
        script = asset.read_text(encoding="utf-8")
        script = re.sub(r"</script", r"<\/script", script, flags=re.IGNORECASE)
        kept_attrs = re.sub(
            _ATTR_RE_TEMPLATE.format(attr="src"), "", attrs, flags=re.IGNORECASE
        ).strip()
        suffix = f" {kept_attrs}" if kept_attrs else ""
        state.inlined["scripts"] += 1
        return (
            f'<script{suffix} data-bundled-from="{escape(src, quote=True)}">\n'
            f"{script}\n</script>"
        )

    return script_re.sub(replace, html)


def _inline_html_assets(html: str, state: _BundleState) -> str:
    tag_re = re.compile(
        r"<(?P<tag>img|source|video|audio|input|link)\b[^>]*>", re.IGNORECASE
    )

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        name = match.group("tag").lower()
        attr = "href" if name == "link" else ("poster" if name == "video" else "src")
        raw_url = _get_attr(tag, attr)
        if not raw_url:
            return tag
        if name == "link":
            rel = (_get_attr(tag, "rel") or "").lower()
            if not any(value in rel.split() for value in ("icon", "apple-touch-icon")):
                return tag
        asset = state.resolve_asset(raw_url, state.html_dir)
        if asset is None:
            return tag
        if not asset.is_file():
            state.warnings.append(f"asset not found: {raw_url}")
            return tag
        data_uri = _as_data_uri(asset)
        state.inlined["assets"] += 1
        return _set_attr(tag, attr, data_uri)

    return tag_re.sub(replace, html)


def _inline_css_urls(css: str, base_dir: Path, state: _BundleState) -> str:
    url_re = re.compile(
        r"url\(\s*(?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\s*\)", re.IGNORECASE
    )

    def replace(match: re.Match[str]) -> str:
        raw_url = match.group("url").strip()
        asset = state.resolve_asset(raw_url, base_dir)
        if asset is None:
            return match.group(0)
        if not asset.is_file():
            state.warnings.append(f"CSS asset not found: {raw_url}")
            return match.group(0)
        state.inlined["assets"] += 1
        return f"url({_as_data_uri(asset)})"

    return url_re.sub(replace, css)


def _get_attr(tag: str, attr: str) -> str | None:
    match = re.search(
        _ATTR_RE_TEMPLATE.format(attr=re.escape(attr)), tag, flags=re.IGNORECASE
    )
    return match.group("value") if match else None


def _set_attr(tag: str, attr: str, value: str) -> str:
    pattern = _ATTR_RE_TEMPLATE.format(attr=re.escape(attr))
    return re.sub(pattern, f'{attr}="{value}"', tag, count=1, flags=re.IGNORECASE)


def _as_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_workspace_path(workdir: Path, raw_path: str) -> Path | None:
    """Resolve relative or /workspace-prefixed input without allowing escape."""
    normalized = raw_path.strip().replace("\\", "/")
    if normalized == "/workspace":
        relative = ""
    elif normalized.startswith("/workspace/"):
        relative = normalized[len("/workspace/") :]
    elif normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        return None
    else:
        relative = normalized
    return resolve_under_workdir(workdir, relative)


def _guest_path(workdir: Path, path: Path) -> str:
    return f"/workspace/{path.resolve().relative_to(workdir.resolve()).as_posix()}"
