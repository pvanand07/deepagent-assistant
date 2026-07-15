![code-wiki](https://github.com/user-attachments/assets/15ea0805-4091-4d9d-8f92-646e18a55556)

# code-wiki

**Your codebase knows *what*. This wiki captures *why*.**

An agent skill that builds and maintains a knowledge wiki from your source code — not from external documents, not auto-generated from ASTs, but from the decisions, rationale, and gotchas that live in engineers' heads and leave when they do.

> *"We had 230 documentation files across three repos. Seven of them described the same search API. None agreed with each other. None agreed with the code."*

That's the problem we built this to solve.

---

## the story

In April 2026, Andrej Karpathy posted his [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern — a three-layer architecture (raw sources → LLM-maintained wiki → index) for personal knowledge bases. We loved the concept and tried to apply it to our production Laravel monorepo.

It didn't fit. Here's what we found:

**Karpathy's wiki consumes external sources** (papers, articles, tweets). Our "source" was the code itself. We didn't need an LLM to synthesize research papers — we needed it to capture why we chose Scout over Meilisearch, why the region filter uses a direct ID lookup instead of nested `whereHas`, and what breaks when you deploy without restarting the SSR server.

**Auto-generated wikis (DeepWiki, Google Code Wiki) describe structure, not decisions.** They'll tell you `ArticleQueryService` has 12 methods. They won't tell you that `PlaceQueryService` uses an older pattern that causes full table scans, and you should follow the Article pattern, not the Place pattern.

**Session-memory tools (claude-memory-compiler) capture conversations, not verified facts.** They're great at recording what was discussed. They can't verify whether the discussion's conclusions are still true six months later.

**Interview-based bootstraps ask too much.** Early versions of our own tool asked open-ended questions — "why did you choose X?" for every architectural area. Engineers don't want to write paragraphs. They want to say "yes" or "no, actually it's because of Z."

So we built something different.

We researched [10 tools](https://github.com/safishamsi/graphify) [across](https://github.com/kfchou/wiki-skills) [the](https://github.com/mduongvandinh/llm-wiki) [ecosystem](https://github.com/repowise-dev/repowise), took the best practices from each (severity-tiered lint from wiki-skills, token budgeting from llms.txt, decision intelligence from repowise), skipped what didn't fit (knowledge graphs, vector DBs, forgetting curves), and built a wiki system where:

- **Code is the source of truth.** When the wiki says X and the code says Y, the code wins. Always.
- **The agent drafts everything.** It reads the code, hypothesizes the "why," and presents drafts for your approval. You audit — you don't author.
- **Zero infrastructure.** Flat markdown files. No database, no indexing pipeline, no separate server. Works tomorrow, not after a sprint of setup.

We used it on a real project — a Laravel monorepo with 50k articles, 200k photos, 3 sub-projects, and 7 months of doc debt. The wiki reduced agent context-loading tokens by ~90% per task and eliminated an entire class of bugs caused by agents reading stale documentation.

Then we extracted the project-specific parts and packaged the rest for you.

---

## quick start

```
/wiki-init          # scaffold wiki/ (~2 min)
/wiki-bootstrap     # agent scans code, drafts topics, you audit (~10 min)
```

That's it. From zero to a working wiki in under 15 minutes.

**What happens during bootstrap:**

```
Agent: I've scanned your codebase and generated 6 draft wiki topics.
       Each has pre-filled decisions and gotchas based on what I found in the code.

         Topic              Confidence   Key hypothesis
         ─────              ──────────   ──────────────
         search.md          0.7          "Standalone QueryService over base class"
         auth.md            0.8          "Multi-guard Sanctum for API + SPA + admin"
         caching.md         0.5          "Two Redis stores — shared across services?"
         deployment.md      0.6          "Envoy symlink releases, SSR restart needed"

       Review options:
         (a) Show me all drafts — I'll audit each one
         (b) Show me only low-confidence items (< 0.6)
         (c) Auto-approve high-confidence, show me the rest
         (d) Add/remove topics before I review

You:   c

Agent: Auto-approved auth.md (0.8). Showing remaining drafts:

       search.md — I found two query service patterns:
         - ArticleQueryService (standalone, doesn't extend base class)
         - PlaceQueryService (extends BaseSearchQueryService)

       My hypothesis:
         Decision: "Standalone pattern chosen for explicitness"
         Gotcha: "PlaceQueryService still uses old pattern — slow queries"

       Correct? (y/n/correct with: ...)

You:   y — also, PlaceQueryService causes full table scans
       specifically on the region filter

Agent: [updates search.md with verified decisions + your correction]
```

The agent reads the code for facts. It hypothesizes the decisions. You confirm or correct — never write from scratch.

---

## what a topic file looks like

```markdown
---
topic: search-api
status: verified
last-verified: 2026-04-10
confidence_score: 0.9
priority: core
rank: 2
tokens: 350
code-paths:
  - app/Services/ArticleQueryService.php
  - app/Http/Requests/BaseSearchRequest.php
related-topics: [api-standards, caching]
---

## overview
Unified search using three-layer pattern: request validation → thin controller → query service.

## current behavior
- Reference implementation: ArticleQueryService (standalone, doesn't extend base class)
- CSV filter convention: filter[region_id]=1,2,3 parsed into arrays
- Region filter uses direct ID lookup for index performance

## decisions
- Standalone QueryService over base class — why: more explicit, avoids Template Method complexity.
  *Supersedes: BaseSearchQueryService inheritance (removed 2025-12).*
- Direct ID lookup for region filters — why: nested whereHas causes full table scans.

## gotchas
- PlaceQueryService still uses the old base class. If debugging slow place queries, check this first.
- Route URLs are /api/articles on api.domain.com, not /portal/v1/ as older docs claim.

## references
- app/Services/ArticleQueryService.php — reference implementation
```

~350 tokens. An agent reads this in one load and knows what to do, what not to do, and where to look.

---

## commands

| Command | What it does | Your time |
|---|---|---|
| `/wiki-init` | Scaffold `wiki/` directory with index, conventions, log | ~2 min |
| `/wiki-bootstrap` | Agent scans code, drafts topics with hypothesized decisions, you audit | ~10 min |
| `/wiki-lint [--fix]` | Health audit: errors, warnings, info. `--fix` re-verifies stale topics | review only |

Three commands. No build step, no config file, no API keys.

---

## the draft-first model

Most documentation tools either ask you to write everything (you won't) or auto-generate everything (missing the "why"). code-wiki takes a third path:

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   1. DEEP SCAN              agent reads code            │
│      ↓                      detects patterns            │
│   2. DRAFT                  agent writes complete        │
│      ↓                      topics with hypotheses      │
│   3. AUDIT                  you confirm or correct       │
│      ↓                      "y" is a valid answer       │
│   4. FINALIZE               agent applies corrections    │
│                             promotes draft → verified    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**The agent detects three types of high-value signals:**

| Signal | What to look for | Example |
|---|---|---|
| **Architectural shifts** | Two patterns for the same task | `BaseSearchQueryService` exists but `ArticleQueryService` doesn't extend it |
| **Complexity hotspots** | Dense TODOs, high line count, many contributors | A 400-line service with 5 FIXME comments |
| **Boundary layers** | External API clients, webhook handlers, SDK wrappers | `StripePaymentService` + `stripe.php` config |

**Every hypothesis comes with a confidence score:**

| Score | Meaning | Example |
|---|---|---|
| `0.8–1.0` | Strong evidence in code | Git history shows a migration from old to new pattern |
| `0.5–0.7` | Moderate evidence from naming/structure | Service class name suggests intent, but no confirming comment |
| `0.3–0.4` | Best guess from conventions | Agent infers from industry patterns, not project-specific evidence |

You choose how to audit: review everything, review only low-confidence items, or auto-approve high-confidence and focus your time where it matters.

---

## how it stays fresh

Every topic file has `code-paths` in its frontmatter — the specific files and directories it describes. When your workflow detects changes to:

- **Database migrations** overlapping a topic's code-paths → agent re-verifies the topic
- **API routes, controllers, resources** overlapping code-paths → agent re-verifies
- **Refactoring** (explicitly flagged) → agent re-verifies

Re-verification: agent re-reads the code, compares every claim in the topic against current behavior, updates what changed, bumps `last-verified` and `confidence_score`.

**Three triggers for new topics:**

1. **Query-filing** — an agent researches an area and the answer isn't in the wiki. It proposes filing the answer as a new topic. The wiki grows from questions actually asked.
2. **Review-check** — after completing a task, the agent checks if it touched uncovered code areas. If yes, proposes a new topic.
3. **Bootstrap** — the initial creation. Runs once.

`/wiki-lint` catches what triggers miss — draft topics never audited, stale `last-verified` dates, broken cross-references, low confidence on verified topics.

---

## how it compares

```
                    captures     captures     zero        code as       audit, not
                    structure?   decisions?   infra?      source?       interview?

Karpathy LLM Wiki      -           yes         yes          -              -
DeepWiki               yes          -         (server)      yes            -
Google Code Wiki       yes          -         (cloud)       yes            -
repowise               yes        partial    (3 DBs)        yes            -
code-wiki               -          yes         yes          yes           yes
```

Every other tool either auto-generates structure docs (missing decisions) or synthesizes external sources (missing code verification). code-wiki is the only one that captures human decisions **and** verifies facts against code, with nothing but markdown files — and it does it by drafting everything first so you audit instead of author.

---

## what it's not

- **Not auto-generated docs.** It doesn't describe every class and function — your LSP and code graph tools do that better. It describes what they *can't*: why the code is this way.
- **Not a RAG system.** No vector DB, no embeddings. At project scale (<50 topics), flat markdown with an index outperforms retrieval infrastructure.
- **Not for external knowledge.** Use [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for papers and articles. code-wiki is for the knowledge inside your codebase.
- **Not a writing assignment.** You never write from scratch. The agent drafts, you approve or correct.

---

## the philosophy

Most documentation fails because it tries to describe what the code does. The code already does that. Documentation should capture what the code *can't express*:

- **Decisions**: "We chose X over Y because Z." Without this, the next engineer re-evaluates the same options.
- **Superseded approaches**: "This replaces the old pattern from March." Without this, agents find the old pattern in git history and recommend it.
- **Gotchas**: "This looks wrong but is intentional because of A." Without this, someone 'fixes' it and breaks production.
- **Constraints**: "Legal requires session tokens stored this way." Without this, a refactor violates compliance.

If the code can tell you something, the wiki shouldn't repeat it. If only a human knows it, the wiki should capture it — and the fastest way to capture it is to let the agent guess first and have the human correct.

---

## works with

- **Claude Code** — skills in `.claude/skills/`
- **Codex CLI** — via AGENTS.md
- **Cursor** — via `.cursor/rules/`
- **Gemini CLI** — via GEMINI.md
- **Any agent** that can read markdown files

The wiki is just markdown. The skills are just instructions. No vendor lock-in.

---

## project structure

```
code-wiki/
├── SKILL.md                  # entry point for agent skill loaders
├── README.md
├── skills/
│   ├── wiki-init.md          # scaffold wiki/ in any project
│   ├── wiki-bootstrap.md     # draft-first: scan, hypothesize, audit
│   └── wiki-lint.md          # health audit, severity-tiered
└── templates/
    ├── conventions.md         # format spec, triggers, creation rules
    └── topic-template.md      # blank topic file with all sections
```

---

## inspired by

Built on ideas from across the ecosystem:

- [Andrej Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the three-layer architecture (raw → processed → index)
- [llms.txt standard](https://llmstxt.org/) — priority tiers and token budgeting for LLM consumption
- [wiki-skills](https://github.com/kfchou/wiki-skills) — severity-tiered lint and query-filing pattern
- [repowise](https://github.com/repowise-dev/repowise) — decision intelligence and staleness tracking from code
- [Graphify](https://github.com/safishamsi/graphify) — WHY-comment extraction from code annotations
- [claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler) — session-based knowledge compilation

We researched all of them, took what worked for codebase wikis, and left what didn't.

---

## license

MIT
