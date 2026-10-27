## Prompt (reconstructed)

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

**Final diff:** 19 changed files; 629 added lines; 0 deleted lines.

**Final commit:** [`2fe48eebab445955efb596a012b7ec96ecd0d9f4`](https://github.com/ru-aish/Fusion-Integrated/commit/2fe48eebab445955efb596a012b7ec96ecd0d9f4).

## Changes in the final commit

- Added the leave request and balance models, initial migration and API routes.
- Scoped records to the authenticated employee and enforced module/action permissions.
- Made employee identity and initial request status server-controlled; disabled update/delete.
- Added basic date validation and usable request-submission/list and balance pages.
- Registered the module/navigation and synchronized permissions and OpenAPI documentation.

## Validation summary

Retrospective verification on the preserved Phase-1 commit, run on 27 October
2026 using an isolated source archive, PostgreSQL 16 and synthetic IAM sessions.
The seven tests were created for this verification; they were not part of the
original Phase-1 commit. No application code was changed to make them pass.

**Result: 7 passed, 0 failed.**

1. Valid creation succeeds; spoofed owner/status are ignored in favor of the authenticated employee and pending status.
2. Request and balance lists exclude other employees; another employee's request detail returns 404.
3. Reversed date ranges return 400 without saving a request.
4. An invalid leave category returns 400 without saving a request.
5. Unauthenticated request/balance access is denied.
6. Missing module grants or action permissions return 403.
7. Request update/delete return 405 and preserve the stored request.

Django system checks, leave migration consistency and permission-manifest
consistency also passed. The API test run took 1.75 seconds; this is validation
time, not original model-generation time.

This small run does not establish approval workflows, automatic balance
accounting, full specification coverage, live institute SSO, or visual frontend
correctness. Those are outside the Phase-1 pilot's verified scope.
