# Agent team protocol

Structured handoffs between orchestrator and subagents. All paths are relative to `/workspace` unless noted.

## Canonical task layout

```
<task_dir>/
  source.md     # research_agent
  spec.md       # output_planner (includes deliverable format)
  output/       # builder deliverables only
```

| Stage | Writes | Reads |
| --- | --- | --- |
| `research_agent` | `<task_dir>/source.md` | user query + `task_dir` |
| `output_planner` | `<task_dir>/spec.md` | `<task_dir>/source.md` when present |
| `builder` | `<task_dir>/output/**` | `<task_dir>/source.md`, `<task_dir>/spec.md` |

Do **not** use `brief.md`, `research/brief.md`, `output.format`, or `build/` for new work.

### `spec.md` requirements

- Declare the deliverable **format** clearly near the top (e.g. `Format: html-report`).
- Allowed format keywords include: `html-report`, `markdown`, `slides-html`, `slides-pptx`, `react-app`, `canvas`, `docx`, `xlsx`, `pptx` — pick what fits; these are not exhaustive.
- Specify file layout under `output/`, acceptance criteria, and out-of-scope items.

## Handoff shape

Every `task` handoff description should include these fields (plain text or fenced block):

```
task_dir: <relative-path>
inputs: <comma-separated existing paths under task_dir, or none>
outputs: <comma-separated expected paths under task_dir>
blocked: false
```

When blocked:

```
task_dir: <relative-path>
blocked: true
error: <short reason>
```

## Blocker tokens

Emit exactly one of these tokens in the final delivery when stuck:

| Token | Who | When |
| --- | --- | --- |
| `BUILD_BLOCKED` | builder | Missing facts/assets in `source.md` / `spec.md`; do not re-research |
| `VALIDATION_BLOCKED` | builder | Required validation failed or tooling unavailable |

Orchestrator: pause the pipeline on a blocker; do not claim completion.

## Preview

Offer preview for validated HTML under `<task_dir>/output/` (typically `output/index.html`).
