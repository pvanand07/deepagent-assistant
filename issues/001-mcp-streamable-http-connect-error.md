# MCP streamable HTTP `ConnectError` during chat

| Field | Value |
| --- | --- |
| **ID** | 001 |
| **Status** | open |
| **Severity** | medium |
| **Area** | MCP integration (`src/deep_agent/integrations/mcp.py`) |
| **Observed** | 2026-07-16 |
| **Environment** | local uvicorn `127.0.0.1:8080`, Windows |

## Summary

During a chat run, the MCP client logged `Error in post_writer` with `httpx.ConnectError` while establishing TLS to a remote streamable-HTTP MCP server. The FastAPI chat endpoint still returned `202 Accepted`; the failure was logged by the MCP SDK background writer, not raised as a handled app error with a clear host URL.

## Reproduction timeline (from server log)

1. `POST /api/sessions/bac1a4f3…/chat` → run `0b8d2445…` accepted
2. User cancelled that run
3. New session `af1c50a1…` created
4. `POST …/chat` → run `d3f8c25e…` accepted + events stream opened
5. Immediately: `Error in post_writer` → `httpx.ConnectError` at `start_tls`
6. Later chat on the same session continued (run `a5060cef…`), so the API stayed up

## Stack trace (abbreviated)

```
Error in post_writer
  mcp/client/streamable_http.py → post_writer → _handle_post_request
  httpx AsyncClient.stream / send
  httpcore connection._connect → stream.start_tls
httpcore.ConnectError
→ httpx.ConnectError
```

Failure point: TLS handshake (`start_tls`), not HTTP status / JSON-RPC parse. Exception message was empty (no hostname in the log line).

## Config involved

`.mcp.json` servers loaded at chat time via `SessionManager._get_mcp()` → `load_mcp_tools()` → `MultiServerMCPClient`:

- `iresearcher` → `https://iresearcher-mcp.elevatics.site/mcp` (Bearer auth)
- `context7` → `https://mcp.context7.com/mcp`

Transport normalizes to `http` / streamable HTTP when no explicit type is set.

## Investigation notes

- Both endpoints respond successfully to MCP `initialize` POSTs when probed manually.
- `load_mcp_tools()` succeeds locally and returns 7 tools (5 iresearcher + 2 context7).
- So this looks **transient** (network blip, remote reset, or overlapping connect after cancel), not a permanently bad URL/config.

## Problems to fix

1. **Opaque logging** — `Error in post_writer` does not include which MCP server URL failed.
2. **Cancel / overlap** — cancelling a run while MCP session setup is in flight may leave background `post_writer` tasks failing noisily.
3. **Partial failure handling** — unclear whether one bad server should fail the whole tool load or degrade to the other server’s tools.

## Proposed follow-ups

- [ ] Log MCP connect failures with server name + URL (wrap `aload_mcp_tools` / per-server connect).
- [ ] Optionally connect servers independently so one `ConnectError` does not poison the other.
- [ ] On cancel, ensure MCP client sessions/tasks are closed cleanly.
- [ ] If flaky host is identified, document timeout/retry or allow disabling that server in UI/settings.

## Related code

- `src/deep_agent/integrations/mcp.py` — `load_mcp_tools`, `aload_mcp_tools`, `load_mcp_connections`
- `src/deep_agent/chat/sessions.py` — `_get_mcp`, MCP cache
- `src/deep_agent/agent_factory.py` — `build_agent` MCP load path
- `.mcp.json` — remote server definitions
