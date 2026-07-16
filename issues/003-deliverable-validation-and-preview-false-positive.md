# Deliverable validation and preview false positives

| Field | Value |
| --- | --- |
| **ID** | 003 |
| **Status** | open |
| **Severity** | high |
| **Area** | Artifact validation and preview serving |
| **Observed** | 2026-07-16 |

## Summary

The landing-page run was reported as successfully validated even though the validation command failed and the preview served a missing JavaScript asset.

## Evidence

- The HTML validation command failed with `PermissionError`.
- `node --check` could not run because Node was unavailable in the sandbox.
- The fallback check only inspected file metadata; it did not parse HTML or JavaScript.
- The server log recorded `GET /script.js` as `404 Not Found`.
- The final response nevertheless stated that required files and validation were complete.

## Impact

- Broken or partially validated deliverables can be presented as done.
- Preview buttons may open an HTML file whose relative assets are not served from the same directory.
- Users cannot distinguish a completed validation from a best-effort inspection.

## Proposed fix

- Make validation failures fail the stage, or explicitly return `VALIDATION_BLOCKED`.
- Validate the exact artifact path that will be previewed.
- Serve the whole artifact directory, not only the HTML file.
- Add HTML parsing, JavaScript syntax, asset existence, and responsive browser checks to the narrow validation suite.
- Require the final response to report each skipped or failed check without claiming completion.
