# Agent pipeline path contract drift

| Field | Value |
| --- | --- |
| **ID** | 002 |
| **Status** | open |
| **Severity** | high |
| **Area** | Agent orchestration and deliverable pipeline |
| **Observed** | 2026-07-16 |

## Summary

The orchestrator prompt, agent TOML files, planner specification, and builder handoff use incompatible directory and filename contracts. A research task can therefore complete tool calls while writing artifacts to one location and validating or previewing another.

## Evidence

- `src/deep_agent/agent_factory.py` describes `brief.md`, `spec.md`, and `output/`.
- `agents/research_agent.toml` writes `source.md`.
- `agents/output_planner.toml` writes `spec.md` and `output.format`.
- The planner-generated specification required `build/`.
- The builder handoff requested `output/`.
- Recorded runs attempted reads and writes under both the task root and `/output`.
- The final response linked `output/index.html` even though earlier filesystem checks reported path and permission errors.

## Impact

- Research, planning, building, and preview stages do not share a reliable artifact contract.
- Builders can overwrite or collide with files created by earlier stages.
- Final responses can report paths that were never successfully validated.

## Proposed fix

- Define one canonical layout, for example:
  - `<task_dir>/source.md`
  - `<task_dir>/spec.md`
  - `<task_dir>/output.format`
  - `<task_dir>/build/`
- Update the factory prompt, all agent TOMLs, handoff messages, preview links, and tests together.
- Pass structured handoff fields instead of embedding competing path instructions in free-form descriptions.
- Add a preflight check that asserts every required input and output path before each stage starts.
