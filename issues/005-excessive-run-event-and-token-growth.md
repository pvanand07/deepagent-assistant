# Excessive upstream request and context growth

| Field | Value |
| --- | --- |
| **ID** | 005 |
| **Status** | open |
| **Severity** | medium |
| **Area** | Run event persistence and model context management |
| **Observed** | 2026-07-16 |

## Summary

The provider request dashboard shows a large number of upstream model requests for a small static landing-page task. Most requests are short-output `tool_calls` requests carrying several thousand to tens of thousands of input tokens, indicating repeated context replay across the run.

## Evidence

- The dashboard shows repeated requests between approximately `5,000` and `35,500` input tokens.
- Most requests finish with `tool_calls`, with only occasional `stop` requests.
- Most outputs are below `300` tokens, but several requests produce roughly `2,300`–`6,500` output tokens.
- The dashboard shows many requests within a short period, not one request per user turn.
- Local persistence also recorded event sequence numbers up to `43006`; this is an internal event count and must not be equated directly with provider billing.

## Impact

- Higher latency and provider cost.
- Greater risk of context-window pressure and repeated tool loops.
- Large SQLite event payloads make diagnosis and replay expensive.
- Repeated tool results can cause the agent to reprocess stale history.

## Proposed fix

- Correlate provider request IDs with local run IDs and stages.
- Measure input-token growth per model call and identify which messages/tools cause it.
- Keep full tool output in bounded external logs and persist compact event summaries.
- Add per-run limits for model calls, tool calls, event count, and input tokens.
- Trim or summarize prior tool history before handing it back to the model.
- Emit a clear terminal reason when a budget is reached.
