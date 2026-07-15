---
title: wiki index
last-updated: 2026-07-15
---

# wiki

Canonical reference docs for this project. One topic per file. The code is the source of truth; this wiki stores decisions, rationale, and current-behavior summaries that the code cannot express on its own.

## how to use

- Agents: load a topic file when the task touches code paths it describes.
- Humans: each topic is a 30-second read. Open the one you need.
- One file per topic, hard cap around 500 lines.

## topics

| rank | topic | priority | tokens | status |
|---|---|---|---|---|
| 1 | [runtime-topology](runtime-topology.md) | core | ~280 | verified |
| 2 | [sandbox-microsandbox](sandbox-microsandbox.md) | core | ~380 | verified |
| 3 | [chat-runs-sse](chat-runs-sse.md) | core | ~300 | verified |
| 4 | [persistence-sqlite](persistence-sqlite.md) | core | ~260 | verified |
| 5 | [settings-and-secrets](settings-and-secrets.md) | core | ~280 | verified |
| 6 | [agent-factory-subagents](agent-factory-subagents.md) | core | ~270 | verified |
| 7 | [llm-providers](llm-providers.md) | extended | ~230 | verified |
| 8 | [frontend-vue-static](frontend-vue-static.md) | extended | ~250 | verified |
| 9 | [desktop-packaging-ci](desktop-packaging-ci.md) | extended | ~270 | verified |

## see also

- [conventions.md](conventions.md) — format, triggers, creation rules
- [log.md](log.md) — operation log
- `docs/` — narrative guides (architecture, migrations); wiki captures decisions only
