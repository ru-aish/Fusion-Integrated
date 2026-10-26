# ELM Phase 2 implementation evidence

Date: 2026-10-26. Implementation branch `phase2/elm-pr78` starts at the selected
Phase 1 commit `2fe48eebab445955efb596a012b7ec96ecd0d9f4`.

The synchronized input package was copied intact to the durable location
`/work/Code/Fusion-ELM-Phase2-Inputs/` (17 files; 2.4 MiB). It remains outside the
application commit to avoid mixing source specifications with product assets.

## Implemented and reviewed

- Added CL first-half and second-half choices, and same-application Station Leave
  flag/details, with migration `0002`.
- Rejected reversed date ranges, multi-day/non-CL half-days, missing Station Leave
  details, active pending/approved overlaps, missing balance rows, and requests whose
  category commitments exceed the provisioned balance.
- Applied continuous calendar-day counting to EL/COL/VL and excluded weekends for
  CL/SCL/RH; institute holiday closures remain unavailable without a calendar feed.
- Preserved the opposite-half same-date CL exception while rejecting duplicate
  same-half and full-day overlap.
- Rechecked balance commitments and employee-wide overlap inside a transaction while
  holding the authoritative employee routing profile row. Requests in different
  categories now serialize against the same row.
- Added current HR routing profiles, policy inputs, and published calendar-day inputs.
  New requests fail closed when profile, policy, account, routing actor, RH date, or
  faculty vacation data is absent. Faculty EL is rejected; non-faculty VL is rejected.
- Added substitute consent/decline/replacement, Unit Head CL/RH final decisions,
  higher-sanction recommendations, optional Establishment routing, and final authority
  decisions. Director routing uses a configured Director authority task; mismatched
  actors and unassigned decisions are denied.
- Added assigned task inbox, append-only request transitions, withdraw and substitute
  replacement actions, and a ledger for reservations, releases, and approved debits.
  The client now exposes request status/history, applicant withdrawal/replacement, and
  assigned approval actions.
- Added separate linked records for pre-start cancellation, ongoing EL/COL/VL
  extension, and resumption review. Cancellation rejection leaves the approved source
  unchanged; approval restores its ledger amount. Extension approval posts the
  increment and updates the approved end date. Resumption review records normal, early,
  or late outcomes and adjusts the source period/ledger for early/late returns.
- Enforced current policy caps for CL/RH/SCL/VL, single-date published RH eligibility,
  faculty-only published-vacation VL, and non-faculty EL. Director routing fails closed
  unless the assigned self-sanction actor is the Director.
- Added configurable COL medical-evidence reference requirements (off by default until
  authorized configuration requires evidence; no medical document is stored here).
- Rejected requests whose selected non-continuous dates contain no chargeable weekdays.
- Added atomic, non-empty calendar replacement publication with duplicate-entry
  validation. Draft entries cannot individually publish themselves, and invalid
  replacement data leaves the current published calendar effective.
- Restricted substitute-decline recovery to the single replacement traversal defined
  by the workflow.
- Fixed balance commitments so pending cancellation/resumption records do not reserve
  leave again and an approved extension is counted through its updated parent period
  exactly once.
- Kept IAM Principal ownership and permission enforcement; added API regression tests
  for spoofed owner/status, permissions, overlap, half-days, balance, and required
  Station Leave detail. Updated the client form and OpenAPI contract.

## Commands and observed results

All checks below were invoked through `/work/bin/workspace-run check`.

| Command | Result |
|---|---|
| `uv sync --extra dev` | Passed; installed project/dev dependencies |
| `.venv/bin/ruff check modules/leave` | Passed |
| `.venv/bin/python manage.py check` | Passed; no issues |
| `.venv/bin/python manage.py makemigrations leave` | Generated migration `0002` |
| `.venv/bin/python manage.py makemigrations --check --dry-run leave` | Passed; no model/migration drift |
| `.venv/bin/python manage.py spectacular --file /tmp/elm-openapi-check.yaml --validate` | Passed |
| YAML comparison of `LeaveRequest` and `HalfDayEnum` against generated schema | Passed |
| `python ops/checks/nav_matches_routes.py` | Passed |
| `python ops/checks/no_cross_module_fk.py` | Passed |
| `python ops/checks/contracts_are_plural.py` | Passed |
| `npm ci` | Passed; npm reported 9 dependency advisories (5 moderate, 2 high, 2 critical) |
| `npm run typecheck` | Passed (also rerun within production build) |
| `npm run build` | Passed; Vite emitted the existing large-chunk warning (>500 kB) |
| `npm test -- --maxWorkers=1` | Passed; 4 files, 35 tests |
| `.venv/bin/pytest modules/leave/tests/test_counting.py -q` | Passed; 3 category-counting tests |
| Earlier focused backend run | Superseded by the final 41-test PostgreSQL run below. |
| `.venv/bin/ruff check modules/leave` | Passed after formatting and duplicate-field cleanup |
| `.venv/bin/python manage.py check` | Passed; no issues |
| `.venv/bin/python manage.py makemigrations --check --dry-run leave` | Passed; no model/migration drift |
| `npm run typecheck` | Passed after workflow UI additions |
| `npm test -- --maxWorkers=1` | Passed; 4 files, 35 tests |
| `/work/bin/workspace-run check -- /bin/bash /work/artifacts/fusion-elm-6b/with-db-env.sh .venv/bin/pytest -q --no-header modules/leave/tests fusion_auth/tests --maxfail=1` | Passed: 41 tests on PostgreSQL 16.15, including cross-category contention, IAM assignment denial, cancellation, extension accounting, resumption branches, substitute replacement limit, COL evidence, zero-day dates, and calendar replacement. |
| Clean PostgreSQL database migration to head | Passed through all leave and project migrations including `leave.0008`; temporary database dropped after verification. |
| Phase 1 schema/data upgrade (`leave.0001` + legacy balance/request rows → head) | Passed through `leave.0002`–`leave.0008`; legacy rows remained readable; temporary database dropped after verification. |
| `.venv/bin/python manage.py check` and `makemigrations --check --dry-run` | Passed: no issues and no model/migration drift. |
| `.venv/bin/python manage.py spectacular --file /tmp/elm-openapi-check.yaml --validate` | Passed: no schema warnings or errors. |
| `.venv/bin/ruff check modules/leave` | Passed. |
| `.venv/bin/python ops/checks/nav_matches_routes.py`, `no_cross_module_fk.py`, `contracts_are_plural.py` | Passed: nav/routes agree; no cross-module foreign keys; all contract getters plural. |
| `cd client && npm test -- --maxWorkers=1 && npm run typecheck && npm run build` | Passed: 36 tests including one focused leave-form interaction test, typecheck, production build. Vite emitted the existing >500 kB chunk notice. |

Isolated PostgreSQL 16.15 is available for implementation checks at
`/work/artifacts/fusion-elm-6b/pgsocket`; the task-owned container is named
`fusion-elm-6b-test-postgres`. The first isolated migration was started before the
new schema existed and failed, so migrations `0003` and `0004` were subsequently
applied with `workspace-run check`. The authenticated API behavior was exercised through
Django REST integration tests using synthetic IAM sessions. A bounded Vite browser
preview loaded the Fusion page, but its `/api/v1/me` request returned HTTP 500 because
the configured identity service was unreachable; no authenticated live leave
workflow/API smoke was possible. The shared dev server was stopped after the preview.

## Local model constraint

The experiment notes identify `gpt-oss-20b` as the selected Phase 1 model, but the
local Ollama inventory documented at experiment setup did not include GPT-OSS. A
read-only `ollama list` check returned `could not connect to ollama server`; the
configured runtime was not running. No model server was started and no weights were
downloaded. Consequently, no Phase 2 interaction with the selected local model is
claimed. This implementation and review used the assigned GPT-6 Luna agent and normal
engineering tools; it is not a substitute claim for a local GPT-OSS run.

## Open issues / deployment blockers

The following synchronized requirements are still incomplete: annual entitlement
issuance and year-end carry-forward/lapse/VL-to-EL conversion, idempotent year-end
processing, offline-sanctioned record synchronization, SLA reminders/escalation,
printable/exportable applications, and full admin UX for configuration/import. Calendar
replacement is available through the authorized API, but there is no administrator
editor/import screen. `LeaveBalance` remains a provisioned snapshot: ledger events are
auditable, but year-scoped accounts and reconciliation are not implemented. Production
deployment and authenticated live UI/API smoke are not established.
