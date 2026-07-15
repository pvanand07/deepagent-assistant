---
topic: llm-providers
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: extended
rank: 7
tokens: 230
code-paths:
  - src/deep_agent/integrations/model_provider.py
  - src/deep_agent/integrations/model_catalog.py
related-topics: [settings-and-secrets, agent-factory-subagents]
---

## overview

All LLM providers go through one OpenAI-compatible factory (`ChatOpenAI`): OpenRouter, Ollama, and custom base URLs, with settings JSON as primary config.

## current behavior

- Provider kinds: `openrouter`, `ollama`, custom OpenAI-compatible.
- Settings JSON primary; env still overrides for CI/tests.
- `get_openrouter_model` remains as a backward-compatible alias.
- OpenRouter base URL is fixed; custom override is not applied for OpenRouter.
- Model catalog powers platforms/models UI and API.

## decisions

- Single OpenAI-compatible factory for all providers — why: one code path for chat completions across hosted/local.
- OpenRouter never uses a custom base URL override — why: avoid misconfiguration against openrouter.ai.

## gotchas

- Dual config surfaces: settings platforms vs leftover env keys via `apply_settings_to_environ` — prefer settings UI/JSON.
- Ollama default base `http://127.0.0.1:11434/v1` — desktop users must have Ollama running locally.

## references

- `src/deep_agent/settings/store.py` (platform kinds / base URLs)
