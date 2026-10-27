# Phase 1 — Single broad implementation prompt

This is a reconstructed task prompt based on the recorded assignment context and
final pilot. It is not a verified verbatim execution transcript and does not
establish which model executed it. No intermediate prompt rounds are asserted.

**Recorded final commit:** `2fe48eebab445955efb596a012b7ec96ecd0d9f4`
**Final diff:** 19 changed files; 629 added lines; 0 deleted lines.
**Per-model execution time:** not recorded.

## Prompt

```text
Work on the supplied Fusion Base code in this isolated checkout. Read the
Assignment 6 instructions, the complete ELM specification package (problem
statement, functional requirements, business rules, use cases, workflows and
traceability matrix), and the relevant Fusion setup and module guides before
starting. Inspect the existing code and reference modules so the implementation
fits the project's conventions.

Attempt the initial Employee Leave Management implementation described in those
inputs. Do the implementation work, not only a plan, while respecting any
approval gates in the supplied instructions. Keep it minimal: reuse existing
Fusion services and components, add the module files and necessary integration
entries, and avoid unrelated rewrites, extra abstractions or unnecessary files.
Preserve existing work and do not invent institutional roles, policies or data.

Connect the implemented backend, database models and migrations, permissions,
API routes and frontend pages through Fusion's existing authentication and UI.
Provide usable leave-request submission/listing and balance views as part of the
pilot. If the full specification cannot be implemented, clearly state which
functions are working and which remain incomplete; do not hide missing features.

Check the pilot against these practical cases:
- A valid request can be submitted and appears in the employee's own list.
- Reversed dates and invalid leave categories produce validation errors.
- Another employee's requests and balances are not exposed.
- The client cannot choose another employee's identity or force request status.
- Access without the required login, module grant or permission is denied.
- Request and balance pages handle loading, empty results and API errors.

Run the relevant Django startup, migration-consistency and permission checks,
frontend typecheck/build, and a brief synthetic-account API or application smoke
test. Synchronize generated permission and API-schema files when needed. Report
what actually passed, what failed or could not be run, setup instructions, and
remaining limitations. Never include real credentials or claim unperformed tests.
```
