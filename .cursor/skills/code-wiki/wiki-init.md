---
name: wiki-init
description: Scaffold a wiki/ directory in any project with index, conventions, log, and archive folder.
---

<objective>
Create the wiki infrastructure in the current project. One command, ~2 minutes, fully reversible.
</objective>

<process>

## Step 1: Detect project

- Identify the project root (look for `.git/`, `package.json`, `composer.json`, `Cargo.toml`, `go.mod`, etc.)
- Identify the primary language/framework
- Check if a wiki/ directory already exists (if yes, ask user: reset or skip)
- Check if a docs/ or documentation/ directory exists (note for later bootstrap/scan)

## Step 2: Choose wiki location

Default: `documentation/wiki/` if `documentation/` exists, otherwise `wiki/` at project root.

Ask user to confirm or override.

## Step 3: Create scaffold

Create these files:

### `wiki/index.md`

```markdown
---
title: wiki index
last-updated: {today}
---

# wiki

Canonical reference docs for this project. One topic per file. The code is the source of truth; this wiki stores decisions, rationale, and current-behavior summaries that the code cannot express on its own.

## how to use

- Agents: load a topic file when the task touches code paths it describes.
- Humans: each topic is a 30-second read. Open the one you need.
- One file per topic, hard cap around 500 lines.

## topics

_Run `/wiki-bootstrap` to create initial topics from your codebase._

## see also

- [conventions.md](conventions.md) — format, triggers, creation rules
- [log.md](log.md) — operation log
```

### `wiki/conventions.md`

Use the template from `templates/conventions.md`. Adapt re-verify trigger paths to the detected framework:
- Laravel: `database/migrations/`, `routes/*.php`, `app/Http/Controllers/`, `app/Http/Resources/`
- Rails: `db/migrate/`, `config/routes.rb`, `app/controllers/`
- Node/Express: `migrations/`, `routes/`, `controllers/`
- Generic: `migrations/`, `routes/`, `controllers/`, `handlers/`

### `wiki/log.md`

```markdown
---
title: wiki operation log
last-updated: {today}
---

# wiki operation log

Append-only. Actions: created, updated, re-verified, archived, discovered, lint.

## log

{today} | created | wiki-infrastructure | initial scaffold via /wiki-init
```

### Archive folder

Create `change-logs/archive/` (or `wiki/archive/` if no change-logs directory exists) with a short readme.

## Step 4: Hook setup (optional)

Ask user: "Want a warn-only hook that flags dated files (yyyymmdd-*.md) being written to docs folders?"

If yes, create the hook script adapted to their agent platform:
- Claude Code: `.claude/hooks/` + `settings.json`
- Codex: `.agents/hooks/` or equivalent
- Other: provide the script, let them wire it

## Step 5: Report

Print what was created and suggest next step:
- If existing docs found: "Run `/wiki-scan` to classify your existing docs and propose topics."
- If no docs: "Run `/wiki-bootstrap` to create initial topics from your codebase."

</process>
