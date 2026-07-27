---
name: officecli
description: >
  Create, analyze, proofread, and modify Office documents (.docx, .xlsx, .pptx)
  with the officecli CLI. Use when the user wants to create, inspect, check
  formatting, find issues, add charts, or modify Office documents.
---

# officecli

AI-friendly CLI for `.docx` / `.xlsx` / `.pptx`. Single binary, no Office install.

In this sandbox, `officecli` is **preinstalled** (`officecli --version`). Prefer it
over python-docx / openpyxl / pptx for document work. Run via `execute`.

## Strategy

**L1 (read) → L2 (DOM edit) → L3 (raw XML)**. Prefer higher layers. Add `--json`
for structured output.

**Skill load order** (this file is the entrypoint):

1. **Base (required)** — read exactly one of `word/` · `excel/` · `pptx/` from the
   format or task (`.docx` → word, `.xlsx`/CSV → excel, `.pptx` → pptx).
2. **Advanced (optional)** — for specialized work, also read the matching nested
   skill **on top of** that base (inherits base rules + Delivery Gate). Do not
   skip the base; do not swap in an advanced skill alone.

## Help (IMPORTANT)

When unsure about property names, value formats, or syntax, **run help — do not
guess**:

```bash
officecli help                         # all commands
officecli help docx paragraph          # full element schema
officecli help docx set paragraph      # verb-filtered props
officecli help xlsx pivottable --json  # machine-readable schema
```

Aliases: `word`→`docx`, `excel`→`xlsx`, `ppt`/`powerpoint`→`pptx`.

## Resident mode

Commands auto-start a resident (60s idle). For longer sessions:

```bash
officecli open report.docx
officecli set report.docx ...
officecli close report.docx   # flush + release
```

Flush (`save` / `close`) only before a **non-officecli** reader touches the file.

### File-locking

- Close or save resident files before another tool reads or replaces them.
- Use unique filenames or build directories for retries; do not overwrite open files.
- Treat `permission_denied` or `already exists` as a possible resident-file lock.
- Validate decks with `officecli validate` and `view issues`; binary previews may reject valid PPTX files.

### Preview and delivery

- Create HTML previews with `officecli view <file> html > <file>.preview.html`.
- Offer the generated HTML as the in-app preview artifact.
- Keep the original Office file available for download or OS-native opening.
- Close the resident Office file before generating or serving the HTML preview.

## Quick start

```bash
# PPT
officecli create slides.pptx
officecli add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
officecli add slides.pptx '/slide[1]' --type shape --prop text="Revenue grew 25%" \
  --prop x=2cm --prop y=5cm --prop font=Arial --prop size=24 --prop color=FFFFFF

# Word
officecli create report.docx
officecli add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
officecli add report.docx /body --type paragraph --prop text="Revenue increased 25% YoY."

# Excel
officecli create data.xlsx
officecli set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
officecli set data.xlsx /Sheet1/A2 --prop value="Alice"
```

## L1 — create / read / inspect

```bash
officecli create <file>
officecli view <file> <mode>          # outline | stats | issues | text | annotated | html
officecli get <file> <path> --depth N # [--json]
officecli query <file> <selector>
officecli validate <file>
```

Prefer stable IDs from `get`/`query` (`shape[@id=…]`, `p[@paraId=…]`) over positional
indices in multi-step edits — indices shift on insert/delete.

Always quote paths: `'/slide[1]'` (shell glob-expands brackets).

## L2 — DOM ops

```bash
officecli set <file> <path> --prop key=value [--prop ...]
officecli set <file> <path> --find weather --prop bold=true --prop color=red
officecli set <file> / --find draft --replace final
officecli add <file> <parent> --type <type> [--prop ...] [--after|--before <path>]
officecli add <file> <parent> --from <path>    # clone
officecli move <file> <path> [--to <parent>] [--after|--before <path>]
officecli swap <file> <path1> <path2>
officecli remove <file> <path>
```

Batch (one save cycle):

```bash
officecli batch data.xlsx --commands '[{"op":"set","path":"/Sheet1/A1","props":{"value":"Done"}}]' --json
```

Colors: hex / named / `rgb(...)` / `accent1`… Spacing: `12pt`, `0.5cm`. Dimensions:
`2.54cm`, `1in`, `72pt`. Dotted font aliases: `--prop font.color=red --prop font.bold=true`.

## L3 — raw XML (last resort)

```bash
officecli raw <file> <part>
officecli raw-set <file> <part> --xpath "..." --action replace --xml '<w:p>...</w:p>'
```

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| `--name "foo"` | Use `--prop name="foo"` |
| Unquoted `[N]` paths | Always quote paths |
| Guessing prop names | `officecli help <fmt> <element>` |
| `$` in shell text | Single-quote: `--prop text='$15M'` |
| `\n` in `--prop text` | Use `\\n` |
| PPT `shape[1]` | Usually title placeholder; content is `shape[2]+` |

Paths are **1-based**. `--index` is **0-based** (Excel `add --type row/col` is 1-based).

After edits: `officecli validate <file>` and/or `view issues`.

## Skills (nested)

Prefer nested `SKILL.md` (+ `reference/`). `officecli load_skill <name>` is the
same content when you need the embedded copy.

### Base (always pick one)

| Path | When |
|------|------|
| `word/` | `.docx` — reports, letters, memos, proposals |
| `excel/` | `.xlsx` / CSV — sheets, trackers, light charts |
| `pptx/` | `.pptx` — generic decks, board / sales / product |

### Advanced (on top of the matching base)

| Path | Base | When |
|------|------|------|
| `academic-paper/` | `word/` | Journal / thesis / citations |
| `word-form/` | `word/` | Fillable forms / content controls |
| `financial-model/` | `excel/` | 3-statement / DCF / LBO / projections |
| `data-dashboard/` | `excel/` | Multi-KPI / chart dashboards |
| `pitch-deck/` | `pptx/` | Fundraising / investor decks only |
| `morph-ppt/` | `pptx/` | Cross-slide Morph motion |
| `morph-ppt-3d/` | `pptx/` (+ morph) | 3D Morph / GLB scenes |

One advanced skill per artifact. `morph-ppt-3d/` implies `morph-ppt/` rules too.

Upstream: https://github.com/iOfficeAI/OfficeCLI/tree/main/skills
