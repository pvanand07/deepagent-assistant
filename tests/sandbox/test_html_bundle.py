"""Tests for single-file HTML bundling."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from deep_agent.sandbox.html_bundle import bundle_html_file
from deep_agent.sandbox.tools import build_sandbox_tools


def test_bundle_inlines_local_css_script_and_assets(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "pixel.png").write_bytes(b"\x89PNG\r\n")
    (site / "styles.css").write_text(
        ".hero{background:url('pixel.png')}", encoding="utf-8"
    )
    (site / "app.js").write_text("window.ready = true;", encoding="utf-8")
    (site / "index.html").write_text(
        """<!doctype html>
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="https://example.com/remote.css">
<img src="pixel.png" alt="">
<script src="app.js"></script>
""",
        encoding="utf-8",
    )

    result = bundle_html_file(tmp_path, "site/index.html")

    output = site / "index.single.html"
    bundled = output.read_text(encoding="utf-8")
    encoded = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    assert result["output_path"] == "/workspace/site/index.single.html"
    assert result["inlined"] == {"stylesheets": 1, "scripts": 1, "assets": 2}
    assert result["external_dependencies"] == ["https://example.com/remote.css"]
    assert f"data:image/png;base64,{encoded}" in bundled
    assert "window.ready = true;" in bundled
    assert 'href="styles.css"' not in bundled
    assert 'src="app.js"' not in bundled


def test_bundle_refuses_workspace_escape_and_existing_output(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>Hello</p>", encoding="utf-8")

    with pytest.raises(ValueError, match="within /workspace"):
        bundle_html_file(tmp_path, "../outside.html")
    with pytest.raises(ValueError, match="within /workspace"):
        bundle_html_file(tmp_path, "index.html", "../outside.html")

    (tmp_path / "index.single.html").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        bundle_html_file(tmp_path, "index.html")
    assert (tmp_path / "index.single.html").read_text(encoding="utf-8") == "keep"


def test_bundle_html_tool_is_registered() -> None:
    assert "bundle_html" in {item.name for item in build_sandbox_tools()}
