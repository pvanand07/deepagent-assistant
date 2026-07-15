---
title: wiki conventions
last-updated: {today}
---

# wiki conventions

## file format

Every topic file starts with YAML frontmatter:

- `topic` — kebab-case name, matches filename without extension
- `status` — `draft` (agent-generated, not yet audited) or `verified` (human-audited). Topics created by `/wiki-bootstrap` start as `draft` and move to `verified` after audit. `/wiki-lint` flags draft topics as warnings.
- `last-verified` — date (yyyy-mm-dd) when last checked against code
- `confidence_score` — float 0.0-1.0 indicating confidence in the topic's accuracy. `0.8-1.0` = strong code evidence or human-verified. `0.5-0.7` = moderate evidence from naming/structure. `0.3-0.4` = agent best guess. Verified topics should be 0.8+. Used by agents to decide whether to trust a topic without re-reading code.
- `priority` — `core` (loaded by default) or `extended` (on demand)
- `rank` — integer 1-10 within the priority tier. 1 = most important. Agents under token pressure load top-N by rank instead of all-core. Optional; unranked topics sort after ranked ones.
- `tokens` — approximate token count of file body
- `code-paths` — list of repo-relative paths the topic covers
- `related-topics` — list of other topic names

Body sections (in order):

- **overview** — one or two sentences. What this topic is.
- **current behavior** — bullet points, facts only, each verifiable in code.
- **decisions** — decision → why → when-not-to-apply. When a decision is reversed, add a supersession note: *"Supersedes: {old approach} (removed in {task/date})."* This prevents agents from finding the old approach in history and treating it as current.
- **gotchas** — known traps, edge cases, past incidents.
- **references** — code paths, related topics, external links.

No flowing paragraphs that repeat what structured data already shows.

## size rules

- Hard cap: ~500 lines per topic file.
- Over cap → split into two topics.
- Under ~30 lines → belongs as a section in an existing topic.

## re-verify trigger

A topic is stale when any of these are true:

1. **Database change** — task modifies `{migration-path}` overlapping the topic's code-paths.
2. **API change** — task modifies `{route-path}`, `{controller-path}`, `{resource-path}` overlapping code-paths.
3. **Refactor flag** — task marked `[REFACTOR]` touches code-paths.
4. **Manual audit** — `/wiki-lint --fix` or manual re-verify.

Adapt the paths above to your framework (Laravel, Rails, Express, etc.) during `/wiki-init`.

## new topic creation

Default: update existing. New topic justified when:
- Genuinely new subsystem that doesn't fit existing topics
- Cross-cutting concern emerging repeatedly
- Consolidation reveals one topic was actually two

New topics require human approval.

### when to propose new topics

Three triggers, each catching a different case:

**1. Query-filing (demand-driven).** When any agent asks "how does X work?" or researches an area to complete a task, and the answer isn't covered by any wiki topic — the agent should propose filing that answer as a new topic or a gotcha addition. The wiki grows from questions actually asked, which means it grows toward what people need.

**2. Review-check (supply-driven).** After completing any task, the agent checks:
- Did this task touch code in an area no wiki topic covers? (compare changed files against all topics' `code-paths`)
- Did I discover a gotcha, decision, or constraint worth preserving?

If yes to either → propose a new topic or addition to an existing topic.

**3. Bootstrap (day zero).** `/wiki-bootstrap` creates the initial set by reading the codebase and interviewing the human. This only runs once.

No single trigger catches everything. Query-filing catches "I needed this and it wasn't there." Review-check catches "I changed this and nothing documented it." Bootstrap catches "we're starting from zero."

## backlink audit

When a new topic is created or a topic's name changes:
1. Scan all existing topics for mentions of the new/changed topic name in their content
2. Propose adding `related-topics` entries in both directions (the new topic links to existing, existing link back)
3. This keeps cross-references bidirectional and discoverable

`/wiki-lint` checks for one-directional related-topics (A links to B but B doesn't link to A) as a warning.

## not in scope

- Session notes → change-logs/
- Unimplemented plans → change-logs/
- Things code already makes obvious → nothing (use LSP, code graph tools)
- Dated files (yyyymmdd-*.md) → never in wiki

## wiki updates

When an agent updates a topic file:
1. Show the diff before writing
2. Append the diff to log.md
3. Bump `last-verified` and update `tokens`

## discovery filing

When a review/task discovers behavior no wiki topic covers:
1. If it fits an existing topic → propose adding to gotchas or decisions
2. If it doesn't fit → propose new topic for human approval
3. Append proposal to log.md regardless of approval

## source of truth

When the wiki and the code disagree, code wins. Wiki gets updated to match, never the other way around.
