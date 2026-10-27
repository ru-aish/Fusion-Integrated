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

## Remaining implementation pass evidence

The bounded follow-up pass adds the following features and regression evidence:

| Trace | Implementation and verification |
|---|---|
| CFR-EL-004–009, CFR-EL-028; BR-EL-002–009 | Added year-scoped employee/category accounts, audited opening snapshot migration, transaction reconciliation, explicit annual issuance, unique year runs, audited admin adjustments, per-year cross-boundary reservations/debits, CL/RH/SCL lapse, EL/COL carry-forward, and fractional faculty VL-to-EL conversion. PostgreSQL tests cover multiple-request annual caps, cross-year account slices and ledger reconciliation, issuance/year-close replay, lapse/carry-forward, and retry after an exception. |
| CFR-EL-027 | Added permission-gated offline sanction synchronization with provenance validation, configured employee/hierarchy checks, no workflow relaunch, balance debit/audit, external-ID serialization, idempotent replay, changed-content conflict, denial, and rollback tests. |
| CFR-EL-029, CFR-EL-031–032 | Added per-role SLA thresholds, deterministic processor/task, one-time reminders/escalations through Fusion’s notification outbox, and routing changes only to configured higher authorities. Tests cover threshold processing, routing and repeated runs. |
| CFR-EL-022–023 | Added owner/assigned-official request history, application print and JSON export, and substitute field scoping across list/detail/history/action/export. PostgreSQL tests assert assigned substitutes cannot read evidence identifiers, reasons, or station details. |
| CFR-EL-024–026 | Added permission-gated configuration UI for HR/hierarchy profiles, policy, atomic calendar replacement, offline sanction import, accounts/adjustments/year-end issuance, and SLA configuration/processing. Frontend interaction test submits a profile; T3 preview loaded the page and all six backing APIs returned 200 under isolated synthetic authentication. |
| Cross-cutting contract/upgrade | Generated `openapi/fusion-integrated.v1.yaml` describes the new endpoints and request fields; generated permission catalogue includes the new grants/navigation. Verified a clean migration, populated Phase 1 (`leave.0001`) upgrade, and populated pre-account (`leave.0008`) upgrade. Legacy balance/request/debit rows remained present; the test debit reconciled an 8.00 snapshot to a 5.00 opening account without replaying the debit. |

All annual amounts use the approved baseline values in the synchronized problem
statement: CL 8, RH 2, SCL up to 15, non-faculty EL 30, faculty VL 60, and COL 20.
Unused CL/RH/SCL lapse; unused VL converts 2:1 including fractional conversion;
EL/COL carry forward. Existing legacy `LeaveBalance`/ledger/request rows are retained.
The account migration establishes its opening balance from the legacy snapshot after
subtracting current-year debit/adjustment lifecycle events; those old rows are not
replayed into the new account ledger.

Final focused verification for this pass:

- PostgreSQL 16.15 backend/IAM regression suite: **55 passed** with
  `/work/bin/workspace-run check -- bash /work/artifacts/fusion-elm-6b/with-db-env.sh .venv/bin/pytest -q --no-header modules/leave/tests fusion_auth/tests --maxfail=1`.
- Frontend: **38 tests passed**, TypeScript check passed, production build passed;
  run through `workspace-run check`. Vite reported the existing >500 kB main-chunk
  advisory.
- Ruff passed for changed Python source; Django system checks and
  `makemigrations --check --dry-run` passed; `spectacular --fail-on-warn` generated
  a byte-for-byte matching committed OpenAPI schema; permission manifest check,
  nav/route, module-FK, and plural-contract checks passed.
- Three disposable PostgreSQL databases passed clean migration to head, populated
  Phase 1 schema/data upgrade from `leave.0001`, and populated `leave.0008` lifecycle
  snapshot reconciliation. All temporary databases were dropped afterward; the
  task-owned test database/container remains available.
- T3 preview authenticated through the temporary local synthetic IAM and rendered
  `/leave/configuration`; `/api/v1/me` and the six configuration backing APIs returned
  200. The task-owned dev unit was stopped after the smoke.

## External prerequisites and limits

- The institution-specific year-end boundary is now a required policy configuration
  (month and day together). It intentionally has no assumed default; scheduling fails
  closed until authorized HR configures it. Annual account years and entitlement caps,
  including SCL's calendar-year cap, remain January–December.
- Profiles and calendars are maintained through authorized ELM configuration screens;
  an upstream HR or Academic Calendar feed is not connected in this pass. Production
  use requires approved profile/hierarchy data and published calendars.
- Configured Fusion IAM was unreachable. Browser/API smoke used an ephemeral synthetic
  IAM implementing the repository's documented endpoint contract on a private local
  port. It exercised Fusion’s real session middleware, cookie, CSRF, API, route and UI;
  it is not institute SSO. Live SSO still requires the external IAM service.
- The selected local `gpt-oss-20b` runtime remained unavailable. No model weights were
  downloaded and no interaction with that model is claimed; this work used the assigned
  GPT-6 Luna agent.

## Correctness follow-up for PR78

The independent QA findings against `58a4c43887aa4b4301497fbe0405dd4a74551e9b`
were addressed in this follow-up:

- **Year close and pending balance changes:** close now locks employee profiles,
  checks all affected calendar account years (including cancellation/resumption child
  requests by their current parent dates), and preflights every account before changing
  any balance. If any relevant workflow is pending, the run records exceptions and
  changes no accounts. A retry after resolution processes all accounts once. New leave,
  offline sanctions, cancellations, resumptions, and direct admin adjustments targeting
  a successfully closed calendar year return an explicit audited-reconciliation error.
  The same employee-profile lock serializes workflow submission/adjustment against close.
- **Substitute routing:** acceptance completes the substitute task and creates the next
  authority task in the same database transaction as the state transition and history.
  Unit Head tasks are now visible/actionable for CL/RH final decisions and higher leave
  recommendations; director requests route to the configured authority. Task notification
  outbox errors roll back the transition.
- **Boundary meaning and scheduling:** policy stores validated `year_end_month` and
  `year_end_day`; the configuration API, HR UI, migration, and OpenAPI document these
  fields. February 29 is rejected because the trigger must occur annually. At the
  configured local date, the scheduled task closes the immediately preceding calendar
  account year; before that year's boundary it targets the prior calendar year. Missed
  executions within that boundary period coalesce to that target year and run replay is
  idempotent. The task processes one target year per invocation; if multiple boundary
  periods were missed, older years are not auto-backfilled. HR must review older account
  years and use the explicit year-close control to process them in order.
- **Lint:** added a pinned ESLint 10/TypeScript/React Hooks toolchain and flat config.
  `npm run lint` passes with zero errors. It reports 40 warnings in existing code: React
  Fast Refresh export patterns, two synchronous state updates in effects, and existing
  `any` annotations in the configuration page. These are warnings so the initial scoped
  lint baseline does not trigger unrelated cleanup.

Final follow-up verification on PostgreSQL 16.15:

- `/work/bin/workspace-run check -- /bin/bash /work/artifacts/fusion-elm-6b/with-db-env.sh .venv/bin/pytest -q --no-header modules/leave/tests fusion_auth/tests --maxfail=1` — **63 passed**.
- `/work/bin/workspace-run check -- npm test -- --maxWorkers=1` — **38 passed** in 6 files; `npm run typecheck`, `npm run build`, and `npm run lint` passed. Vite still reports the 502.53 kB main chunk warning.
- Django `check`, `makemigrations --check --dry-run`, focused Ruff, permission manifest, route/navigation, module-FK, plural-contract, and generated OpenAPI comparison all passed. The new migration `0013_leavepolicy_year_end_day_leavepolicy_year_end_month` applied to the task PostgreSQL database.
- Permanent regression tests include the cancellation-after-close and early-resumption repros, no partial account processing during a deferred close, replay/idempotency, rejection of closed-year submissions/offline records/resumptions/cancellations/admin adjustments, timezone boundary behavior, missing configuration, substitute denial, Unit Head inbox actions for CL and higher leave, authority approval, and replacement-substitute routing.
- T3 preview smoke used the task's synthetic local IAM only (not institute SSO): owner submission, substitute acceptance, Unit Head approval, owner balance/history, and JSON export. Request 3 finished approved; both tasks completed; 2026 CL showed 7 available and reconciled. Synthetic records and the task-owned dev unit were removed/stopped afterward; the PostgreSQL container remains available for review.

## Evidence revision record

This documentation-only revision was added after the verified application commit
`ed91cd0a39c6c00c90d59844a3e960ba178feb71`. It retains the recorded execution
attribution and does not authenticate an unverified replacement model or a
max-reasoning run. The original user-edited source file is retained separately
and has not been overwritten.

The reported 63 backend/IAM tests, 38 frontend tests and seven focused final-review
regressions refer to the previously recorded verification runs. Application code
was not changed and those tests were not rerun for this documentation revision.
The revision was checked for file scope, unchanged application-tree content and
whitespace consistency.
