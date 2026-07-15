---
name: wiki-bootstrap
description: |
  Draft-first bootstrap: agent scans codebase, generates complete topic drafts with hypothesized decisions and gotchas, then presents for human audit. Human corrects or approves — never writes from scratch. Total human effort: 5-15 minutes.
---

<objective>
Bootstrap a wiki using the Propose-Review-Approve model. The agent does the reading AND the hypothesizing. The human audits, corrects, and approves — never writes from scratch. The interaction should feel like an audit, not a writing assignment.
</objective>

<principles>
- **Draft everything.** Write complete topic files — including decisions and gotchas — before asking the human anything. Best guesses are better than blank fields.
- **Hypothesize the "why".** When two patterns exist for the same task, hypothesize which is newer and why. When a boundary layer exists, hypothesize the integration reason. State your confidence.
- **Ask to verify, not to author.** "I assumed X because I saw Y. Correct?" — not "Why did you choose X?"
- **Batch the audit.** Present all drafts at once. Human reviews in one pass.
- **Confidence scores are honest.** High confidence (0.8+) = code evidence is strong. Low confidence (0.3-0.5) = the agent is guessing from naming conventions or sparse signals. Don't inflate.
- **Zero infrastructure.** All state lives in the markdown files. `status: draft` vs `status: verified` is the only tracking mechanism.
</principles>

<process>

## Phase 1: Deep Scan (no human input)

The agent reads the codebase and builds a complete picture before generating any output.

### 1a. Read project structure

- Identify project root (`.git/`, `package.json`, `composer.json`, `Cargo.toml`, `go.mod`, etc.)
- Identify primary language/framework
- List top-level directories
- Find key config files (database, cache, queue, auth, search)
- Find route definitions, model/entity definitions, service/business-logic directories
- Count: models, routes, services, migrations, tests

### 1b. Identify architectural areas

Group findings into areas. Standard detection:

| Area | How to detect |
|---|---|
| Auth/SSO | auth config, middleware, guards, login routes |
| Database/Models | migrations, models, relationships |
| API/Routes | route files, controllers, resources |
| Search | search service, Scout/Elasticsearch/Algolia config |
| Caching | cache config, Redis config, cache service |
| File/Media | upload handlers, storage config, media models |
| Background jobs | queue config, job classes |
| Frontend | JS framework, components, pages |
| Deployment | deploy scripts, CI config, Dockerfiles |
| Testing | test directories, test config |
| External integrations | API clients, webhooks, third-party SDKs |

Only list areas that actually exist in the code.

### 1c. Detect high-value context markers

Scan for three categories of signal that produce the richest wiki topics:

**Architectural shifts** — two different patterns for the same task.
- Look for: a base class AND standalone implementations of the same concern, deprecated/legacy modules alongside replacements, commented-out imports, migration files that rename or drop tables.
- Example signal: `BaseSearchQueryService` exists but `ArticleQueryService` doesn't extend it → likely an architectural shift from inheritance to standalone.

**Complexity hotspots** — files where tribal knowledge concentrates.
- Look for: files with high line count (>300 lines), methods with deep nesting, dense TODO/FIXME/HACK comments, files touched by many contributors (if git history available via `git log --format='%an' -- {file} | sort -u | wc -l`).
- Example signal: A service file with 5 TODO comments and 400 lines → likely accumulated workarounds worth documenting.

**Boundary layers** — intersections with external systems.
- Look for: API client classes, webhook handlers, SDK wrappers, config files referencing external service URLs/keys, queue jobs that call external APIs.
- Example signal: `StripePaymentService` + `stripe.php` config → payment integration boundary worth documenting.

### 1d. Auto-draft current behavior per area

For each detected area, write bullet-point "current behavior" by reading the code:
- What framework/library is used
- How it's configured
- What entities/routes/services exist
- How they connect

This is fact-only, verifiable in code. No interpretation needed.

### 1e. Hypothesize decisions and gotchas

This is the core of Draft-First. For each area, the agent generates its best interpretation:

**For decisions**, look at code evidence and hypothesize:
- If two patterns exist: "Chose {newer pattern} over {older pattern} — likely because {reason from code evidence}."
- If a non-obvious library choice: "Uses {X} instead of the more common {Y} — possibly because {reason}."
- If a config deviates from framework defaults: "Overrides default {setting} — likely to handle {scenario}."

**For gotchas**, look at code evidence and hypothesize:
- If a file has FIXME/TODO/HACK: "Known issue: {paraphrased comment}."
- If two similar implementations differ: "{A} uses pattern X but {B} uses pattern Y — may cause confusion."
- If a config has an unusual value: "Setting {X} is non-default — changing it may break {Y}."

**Assign confidence scores:**
- `0.8-1.0` — Strong code evidence. Two patterns clearly exist, git history shows a migration, config comments explain the choice.
- `0.5-0.7` — Moderate evidence. Naming conventions suggest intent, but no explicit confirmation in code.
- `0.3-0.4` — Weak evidence. Agent is guessing from structure, file organization, or common industry patterns.

## Phase 2: Draft Generation (no human input)

### 2a. Generate topic files with draft status

For each area with enough substance (skip areas that are pure "standard setup" with no detectable shifts, hotspots, or boundaries), create a topic file:

```markdown
---
topic: {area-name}
status: draft
last-verified: {today}
confidence_score: {0.0-1.0, area-wide average}
priority: core
tokens: {estimate}
code-paths:
  - {relevant directories}
related-topics: [{other areas}]
---

## overview
{one sentence summary from scan}

## current behavior
{bullet points — facts from code, no interpretation}

## decisions
{hypothesized decisions with confidence markers}
- {decision} — why: {agent's hypothesis}. confidence: {high|medium|low}. evidence: {what in the code suggests this}.

## gotchas
{hypothesized gotchas with confidence markers}
- {gotcha} confidence: {high|medium|low}. evidence: {what in the code suggests this}.

## references
{code paths from scan}
```

### 2b. Write files to wiki/

Create all topic files in the wiki directory with `status: draft`. These are real files, not previews — the human will audit them in place.

### 2c. Generate draft index

Update `wiki/index.md` with all draft topics, marked as `[DRAFT]`:

```markdown
## topics

| rank | topic | priority | tokens | status |
|---|---|---|---|---|
| 1 | [search](search.md) | core | ~350 | DRAFT |
| 2 | [auth](auth.md) | core | ~280 | DRAFT |
| ... | ... | ... | ... | ... |
```

### 2d. Auto-rank by signal density

Rank topics automatically by: number of architectural shifts detected + number of complexity hotspots + number of hypothesized gotchas. More signals = higher rank (more knowledge at risk of being lost).

## Phase 3: Audit (5-15 minutes of human input)

### 3a. Present the draft map

Show the human what was generated:

```
I've scanned your codebase and generated {N} draft wiki topics.
Each has pre-filled decisions and gotchas based on what I found in the code.

  Topic              Confidence   Key hypothesis
  ─────              ──────────   ──────────────
  search.md          0.7          "Standalone QueryService chosen over base class inheritance"
  auth.md            0.8          "Multi-guard Sanctum setup for API + SPA + admin"
  caching.md         0.5          "Two Redis stores — one shared across services?"
  deployment.md      0.6          "Envoy symlink releases with SSR restart requirement"

Skipped (standard setup, no signals worth documenting):
  - database (standard ORM, no architectural shifts detected)
  - testing (standard test framework, no unusual patterns)

Review options:
  (a) Show me all drafts — I'll audit each one
  (b) Show me only low-confidence items (< 0.6)
  (c) Auto-approve high-confidence, show me the rest
  (d) Add/remove topics before I review
```

Wait for the human to choose a review strategy.

### 3b. Present drafts for verification

For each topic being audited, show the hypothesized decisions and gotchas with specific yes/no questions:

```
## search.md (confidence: 0.7)

I found two query service patterns:
  - ArticleQueryService — standalone, doesn't extend a base class
  - PlaceQueryService — extends BaseSearchQueryService

My hypothesis:
  ✓ Decision: "Standalone QueryService over base class — chosen for explicitness,
    avoids Template Method complexity."
  ✓ Gotcha: "PlaceQueryService still uses the old base class pattern. If debugging
    slow place queries, check this first."

Questions:
  1. Is the standalone pattern the intended direction? (y/n/correct with: ...)
  2. Is the PlaceQueryService gotcha accurate? Any other gotchas? (y/n/add: ...)
  3. Anything I missed about search? (skip or add)
```

Key rules for audit questions:
- **Never ask "why did you choose X?"** — instead say "I think you chose X because Y. Correct?"
- **Always show the evidence** — "I saw {code pattern}, so I assumed {decision}."
- **Accept "y" as a complete answer** — the human shouldn't need to write sentences.
- **Accept corrections inline** — "n — it's actually because of Z" is a valid response.

### 3c. Process corrections

For each response:
- **"y" or "correct"** → mark the hypothesis as verified, bump confidence to 1.0.
- **"n" + correction** → replace hypothesis with the human's correction, set confidence to 1.0.
- **"skip"** → leave as draft, keep original confidence. Will be flagged by `/wiki-lint`.
- **Addition** → append to the relevant section, set confidence to 1.0 for the added item.

### 3d. One open-ended question at the end

```
Anything else I should know that doesn't fit the topics above?
The "don't touch" list, political constraints, historical debt,
things that look wrong but are intentional?
```

This catches cross-cutting concerns. If the answer produces new material, file it into the most relevant existing topic or propose a new one.

## Phase 4: Finalize (no human input)

### 4a. Update all topic files

For each audited topic:
- Replace hypothesized content with verified/corrected content
- Change `status: draft` → `status: verified`
- Set `confidence_score` to the new average (verified items = 1.0)
- Remove per-item `confidence:` and `evidence:` markers from the body (these were audit scaffolding)
- Bump `last-verified` to today
- Recalculate `tokens`

For topics the human skipped entirely:
- Keep `status: draft` and original `confidence_score`
- These will appear as warnings in `/wiki-lint`

### 4b. Clean up draft artifacts

Remove the `confidence:` and `evidence:` inline markers from verified topics. The final format should match the standard topic template:

```markdown
## decisions
- Standalone QueryService over base class — why: more explicit, avoids Template Method complexity.
  *Supersedes: BaseSearchQueryService inheritance (removed 2025-12).*
```

Not:
```markdown
## decisions
- Standalone QueryService over base class — why: more explicit. confidence: high. evidence: ArticleQueryService doesn't extend base.
```

### 4c. Run backlink audit

For each topic, scan all other topics for mentions of the topic name or its code-paths. Add `related-topics` entries in both directions.

### 4d. Update index.md

Replace `[DRAFT]` markers with verified status. Sort by rank within priority tiers.

### 4e. Update log.md

For each topic:
```
{today} | created | {topic} | wiki-bootstrap: draft-first (scanned + audited)
```

</process>

<output>
Print final summary:
```
Wiki bootstrapped: {N} topics verified, {M} still draft.

  Verified:
    1. search.md — standalone QueryService, PlaceQueryService legacy gotcha (~350 tokens)
    2. auth.md — multi-guard Sanctum, token refresh gotcha (~280 tokens)
    ...

  Still draft (skipped during audit — will appear in /wiki-lint):
    - caching.md (confidence: 0.5)

  Total: ~{total} tokens across all topics.

Next steps:
  - Draft topics will be flagged by /wiki-lint — audit them when ready.
  - Topics re-verify automatically when you change migrations, routes, or controllers.
  - Run /wiki-lint periodically to check health.
  - To add this to your agent's auto-loaded context:
    @{wiki-path}/index.md
```
</output>
