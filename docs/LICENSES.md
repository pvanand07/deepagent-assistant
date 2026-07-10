# Third-Party Licenses & Redistribution

This document summarizes license obligations if you ship Deep Agent as a
binary (or container) that includes [microsandbox](https://github.com/superradcompany/microsandbox)
and related runtimes.

**This is not legal advice.** Confirm with counsel before a commercial release.

## Summary

| Component | License | Ship in a closed-source product? | Main obligation |
|-----------|---------|----------------------------------|-----------------|
| microsandbox | Apache-2.0 | Yes | Attribution + Apache NOTICE |
| libkrun | Apache-2.0 | Yes | Attribution + Apache NOTICE |
| libkrunfw | LGPL-2.1 (library) + GPL-2.0 (bundled kernel) | Yes | **Corresponding source** for libkrunfw + kernel; your app is **not** forced open |
| Python app deps (deepagents, langchain, langgraph, fastapi, …) | Mostly MIT / BSD / Apache-2.0 | Yes | Attribution |
| orjson | MPL-2.0 (+ Apache/MIT) | Yes | Keep notices; publish file-level changes if you modify it |
| Guest OCI images (alpine / python / debian) | Distro + package mix | Usually yes | Respect base-image licenses; avoid Docker trademark misuse |
| This repository’s own code | *(add a project LICENSE)* | You choose | Pick MIT, Apache-2.0, or proprietary terms |

**Bottom line:** You can ship a commercial Mac/Win/Linux binary that embeds
microsandbox. Nothing in the core stack is AGPL. The hard requirement is
offering **corresponding source for libkrunfw and its bundled Linux kernel**.

---

## microsandbox & libkrun (Apache-2.0)

- **microsandbox:** [Apache License 2.0](https://github.com/superradcompany/microsandbox/blob/main/LICENSE)
- **libkrun:** [Apache License 2.0](https://github.com/containers/libkrun/blob/main/LICENSE)

When redistributing (including inside a PyInstaller binary or wheel):

1. Include a copy of the Apache-2.0 license text.
2. Retain copyright and attribution notices.
3. If upstream ships a `NOTICE` file, include its contents in your distribution
   (e.g. under `THIRD_PARTY_NOTICES/`).
4. Do not use upstream trademarks in a way that implies endorsement.

Your own code may remain under a different license (including proprietary).

---

## libkrunfw (LGPL-2.1 + GPL-2.0 kernel) — critical

[libkrunfw](https://github.com/libkrun/libkrunfw) bundles a Linux kernel inside
a dynamic library for libkrun / microsandbox.

Upstream states (paraphrased from their README):

- **Bundled Linux kernel** and kernel **patches:** GPL-2.0-only  
- **Library code** (including generated bundle code): LGPL-2.1-only  
- Distributing **libkrunfw in binary form** requires accompanying the
  **source code of the bundled Linux kernel** and the **library itself**  
- Programs that **link against** libkrunfw are **not** required to be
  GPL-2.0 or LGPL-2.1

### What this means for Deep Agent

| Question | Answer |
|----------|--------|
| Can we keep Deep Agent closed source? | Yes |
| Can we embed `libkrunfw` in the Mac/Linux/Windows binary? | Yes, with source offer |
| Must we open-source Deep Agent? | No (per upstream linking statement) |
| Must we provide libkrunfw + kernel sources? | **Yes** |

### Practical compliance

Ship with every release (or link from the installer / About screen):

1. Exact version of `libkrunfw` / microsandbox you bundled.  
2. A **written offer** or archive of corresponding source for that version
   (Git tag, release tarball, or your own mirror).  
3. Copies of GPL-2.0 and LGPL-2.1 license texts.

Example offer text (adapt paths/URLs):

```text
Corresponding Source Offer — libkrunfw
======================================
This product redistributes libkrunfw, which includes a Linux kernel
(GPL-2.0) and library code (LGPL-2.1).

Corresponding source for the exact build we ship is available at:
  https://github.com/libkrun/libkrunfw/tree/<TAG_OR_COMMIT>
  (and/or a tarball we host: https://example.com/sources/libkrunfw-<ver>.tar.gz)

Offer valid for at least three years from the date of distribution,
or as long as we offer spare parts / support for this product version,
whichever is longer, consistent with GPL/LGPL requirements.
```

---

## Python dependencies (current stack)

Licenses as published on PyPI for packages used by this project (and common
transitives). Re-verify before each release — versions change.

| Package | Typical license |
|---------|-----------------|
| deepagents | MIT |
| langchain, langchain-openai, langchain-mcp-adapters | MIT |
| langgraph, langgraph-checkpoint-sqlite | MIT |
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| httpx, starlette | BSD-3-Clause |
| aiosqlite, python-dotenv | MIT / BSD-3-Clause |
| pydantic | MIT |
| openai | Apache-2.0 |
| microsandbox | Apache-2.0 |
| orjson | MPL-2.0 and (Apache-2.0 or MIT) |

Generate an up-to-date report from a lockfile or venv:

```bash
pip install pip-licenses
pip-licenses --format=markdown --output-file=docs/generated-python-licenses.md
```

---

## Guest OCI / rootfs images

If the binary or first-run flow pulls (or vendors) images such as `alpine`,
`python`, or `debian`:

- Those images contain many packages under mixed licenses (GPL, LGPL, MIT, …).
- Redistributing a **pre-baked rootfs** inside your installer usually means
  documenting that base and offering source where GPL/LGPL packages require it.
- Prefer **first-run pull** from an official registry, or build/publish your
  own image with a clear SBOM and license list.
- Do not imply affiliation with Docker, Inc. without permission; “Docker” is a
  trademark. Prefer “OCI image” / “container image” in product copy when unsure.

---

## Suggested `THIRD_PARTY_NOTICES/` layout

```text
THIRD_PARTY_NOTICES/
  README.md                 # points here / short summary
  NOTICE.txt                # Apache NOTICE aggregations
  LICENSE-Apache-2.0.txt
  LICENSE-MIT.txt
  LICENSE-BSD-3-Clause.txt
  LICENSE-LGPL-2.1.txt
  LICENSE-GPL-2.0.txt
  LICENSE-MPL-2.0.txt
  libkrunfw-SOURCE-OFFER.txt
  python-licenses.md        # from pip-licenses
```

Include this directory next to the binary, or extract it beside the app on
first launch.

---

## Pre-release checklist

- [ ] Project `LICENSE` chosen and committed for Deep Agent itself  
- [ ] `THIRD_PARTY_NOTICES/` populated for the exact versions you ship  
- [ ] Apache NOTICE / attribution for microsandbox and libkrun  
- [ ] libkrunfw + kernel **corresponding source** URL or tarball published  
- [ ] `pip-licenses` (or equivalent) regenerated for the release lockfile  
- [ ] Guest image strategy documented (pull vs vendor) and licensed accordingly  
- [ ] macOS/Windows code signing does not strip required license files  

---

## References

- [microsandbox](https://github.com/superradcompany/microsandbox)  
- [libkrun](https://github.com/containers/libkrun)  
- [libkrunfw license notes](https://github.com/libkrun/libkrunfw#license)  
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)  
- [GNU GPL 2.0](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)  
- [GNU LGPL 2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)  
