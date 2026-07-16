# Cancelled runs and empty error state

| Field | Value |
| --- | --- |
| **ID** | 004 |
| **Status** | open |
| **Severity** | high |
| **Area** | Chat run lifecycle and error reporting |
| **Observed** | 2026-07-16 |

## Summary

Several recent runs were cancelled, while another ended in `error` with an empty persisted error string. The UI/API therefore provides no actionable explanation for whether a run was cancelled, failed during setup, or failed during execution.

## Evidence

- Run `0b8d2445…` was cancelled.
- Run `a5060cef…` was cancelled after another message arrived.
- Run `e927bf52…` was cancelled.
- Run `d3f8c25e…` ended with status `error` and `error: ""`.
- The same period included an MCP background `post_writer` failure during TLS setup.
- Chat requests still returned `202 Accepted` before the eventual run outcome was known.

## Impact

- Users receive no useful failure reason.
- Cancellation can overlap MCP/session setup and leave background work running.
- A later successful chat can obscure that an earlier run failed.
- Support and diagnostics cannot reliably correlate UI state with backend cause.

## Proposed fix

- Preserve structured terminal causes: `cancelled`, `mcp_connect_failed`, `model_failed`, `sandbox_failed`, and `validation_failed`.
- Never persist an empty error; include a safe fallback message and correlation ID.
- Make cancellation propagate to agent, MCP, and background writer tasks.
- Ensure terminal events are emitted exactly once and include run ID, stage, and cause.
- Have the frontend distinguish accepted, running, cancelled, failed, and completed states.
