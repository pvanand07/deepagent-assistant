---
topic: persistence-sqlite
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 4
tokens: 260
code-paths:
  - src/deep_agent/persistence/database.py
related-topics: [chat-runs-sse, settings-and-secrets, runtime-topology]
---

## overview

Three separate SQLite databases under the data dir isolate LangGraph checkpoints, UI message history, and app/run metadata so compaction cannot wipe the chat UI.

## current behavior

- `checkpoints.sqlite` — LangGraph `AsyncSqliteSaver` (may be compacted by summarization).
- `messages.sqlite` — append-only UI chat history; never read from checkpoints for display.
- `app.sqlite` — sessions, runs, durable `run_events` for stream resume.
- Everything runs on the FastAPI event loop (no sync/async bridge).
- Paths honor `DEEPAGENT_DATA_DIR` / per-DB overrides; desktop defaults to AppData `DeepAgent`, dev to repo `data/`.

## decisions

- Triple DB split — why: checkpoint compaction/summarization must not destroy UI history.
- Dropped `AsyncLoopRunner` sync/async bridge — why: run all persistence natively on the app loop. *Supersedes: AsyncLoopRunner.*

## gotchas

- Reconstructing UI from checkpoints is wrong except as a one-time legacy backfill.
- Backup/migrate must treat the three files (plus WAL/SHM) as a set.

## references

- `docs/project-architecture/BUILD_FROM_SCRATCH.md`
