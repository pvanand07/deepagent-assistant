"""Guardrail: orchestrator prompt and agent TOMLs share one path contract."""

from __future__ import annotations

import re
from pathlib import Path

from deep_agent.agent_factory import MAIN_SYSTEM_PROMPT, _REPO_AGENTS_DIR

_REQUIRED_PROMPT = (
    "source.md",
    "spec.md",
    "output/",
    "VALIDATION_BLOCKED",
    "BUILD_BLOCKED",
    "agents/protocol.md",
)


def _toml_bodies() -> dict[str, str]:
    bodies: dict[str, str] = {}
    for path in sorted(_REPO_AGENTS_DIR.glob("*.toml")):
        bodies[path.name] = path.read_text(encoding="utf-8")
    return bodies


def _positive_mentions(text: str, token: str) -> list[str]:
    """Lines that mention token without an explicit negation nearby."""
    hits: list[str] = []
    for line in text.splitlines():
        if token not in line:
            continue
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "no `",
                "no separate",
                "not ",
                "**not**",
                "don't",
                "do not",
                "do **not**",
                "rather than",
                "instead of",
            )
        ):
            continue
        hits.append(line.strip())
    return hits


def test_main_prompt_uses_canonical_layout() -> None:
    prompt = MAIN_SYSTEM_PROMPT
    for token in _REQUIRED_PROMPT:
        assert token in prompt, f"missing {token!r} in MAIN_SYSTEM_PROMPT"
    for token in ("brief.md", "research/brief.md", "output.format"):
        assert not _positive_mentions(prompt, token), (
            f"positive use of forbidden {token!r}: {_positive_mentions(prompt, token)}"
        )
    assert "<task_dir>/build/" not in prompt


def test_agent_tomls_align_with_output_contract() -> None:
    bodies = _toml_bodies()
    assert "research_agent.toml" in bodies
    assert "output_planner.toml" in bodies
    assert "builder.toml" in bodies

    assert "source.md" in bodies["research_agent.toml"]
    assert "spec.md" in bodies["output_planner.toml"]
    assert not _positive_mentions(bodies["output_planner.toml"], "output.format")
    assert "build/" not in bodies["output_planner.toml"] or "not `build/`" in bodies[
        "output_planner.toml"
    ]

    builder = bodies["builder.toml"]
    assert "output/" in builder
    assert "VALIDATION_BLOCKED" in builder
    assert "BUILD_BLOCKED" in builder
    assert not _positive_mentions(builder, "output.format")
    assert "agent-team/protocol.md" not in builder
    assert "agents/protocol.md" in builder


def test_protocol_md_exists_and_matches_contract() -> None:
    protocol = _REPO_AGENTS_DIR / "protocol.md"
    assert protocol.is_file()
    text = protocol.read_text(encoding="utf-8")
    for token in ("source.md", "spec.md", "output/", "VALIDATION_BLOCKED", "BUILD_BLOCKED"):
        assert token in text
    assert not _positive_mentions(text, "output.format")
    assert not _positive_mentions(text, "brief.md")
    assert "Do **not** use" in text
