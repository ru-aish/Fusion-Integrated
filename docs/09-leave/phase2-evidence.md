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
- Rechecked balance commitments inside a transaction while holding the matching
  account row lock, so concurrent same-category submissions cannot both pass against
  a stale balance.
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
| `.venv/bin/pytest modules/leave/tests -q` | Blocked before tests: PostgreSQL at `127.0.0.1:5432` refused connection. All 5 API tests errored during database setup; no assertion executed. |

The migration generation/check also warned that Django could not inspect database
migration history because PostgreSQL was unavailable. A full database migration,
backend integration run, and live app/API smoke were therefore not established.

## Local model constraint

The experiment notes identify `gpt-oss-20b` as the selected Phase 1 model, but the
local Ollama inventory documented at experiment setup did not include GPT-OSS. A
read-only `ollama list` check returned `could not connect to ollama server`; the
configured runtime was not running. No model server was started and no weights were
downloaded. Consequently, no Phase 2 interaction with the selected local model is
claimed. This implementation and review used the assigned GPT-6 Luna agent and normal
engineering tools; it is not a substitute claim for a local GPT-OSS run.

## Open issues / deployment blockers

The complete synchronized baseline includes annual entitlements/lapse/carry-forward,
published RH and Academic Calendar applicability, substitute consent, authority and
Establishment routing, final approval and decision history, withdrawal, cancellation,
extension, resumption, ledger posting, offline synchronization, year-end processing,
SLA reminders/escalation, and printable/exportable applications. These remain absent.
The inherited `LeaveBalance` is a provisioned snapshot, not an auditable transaction
ledger. The implementation does not claim that date counting handles institute
holidays, RH applicability, or faculty/staff eligibility. Approval/accounting and
production deployment should remain blocked until these requirements are designed,
implemented, and verified against the authoritative calendar/hierarchy integrations.
