# Employee Leave Management — Phase 2

This module builds on the Employee Leave Management pilot in
[PR #78](https://github.com/FusionIIIT/Fusion-Integrated/pull/78), extending it
for Assignment 6B. The preserved Phase 1 commit is
[`2fe48ee`](https://github.com/ru-aish/Fusion-Integrated/commit/2fe48eebab445955efb596a012b7ec96ecd0d9f4).

## Implemented scope

- Employee-owned requests and balances, permission enforcement, half-day CL,
  Station Leave details, category-aware counting, overlap and balance validation.
- Configured employee profiles, HR policies and published calendars; substitute
  consent/replacement, authority routing, assigned inbox and request history.
- Withdrawal, cancellation, extension and resumption with ledger accounting.
- Year-scoped accounts, annual issuance, year-end processing, offline sanction
  synchronization, SLA processing, exports/print and administration screens.
- Database migrations, synchronized API and permission contracts, backend and
  frontend regression coverage.

The client routes are `/leave/requests`, `/leave/balances`, `/leave/inbox` and
`/leave/configuration`. API routes are under `/api/v1/leave/`.

## Development records and validation

- [Phase 1 prompt, changes and validation](phase1-prompt-bundles.md) — a
  reconstructed broad prompt, original final commit and seven retrospective tests.
- [Phase 2 prompts, commits and validation](phase2-work-log.md) — recorded
  instruction summaries, corresponding branch commits, review findings and checks.
- [Detailed Phase 2 evidence](phase2-evidence.md) — commands, outcomes,
  requirements, environment limitations and recorded execution attribution.

The recorded final application checks passed 63 backend/IAM tests and 38 frontend
tests, typecheck and production build. Lint completed with zero errors and 40
warnings; the build retained a large-chunk advisory. Clean and populated-database
migration checks passed. Browser QA exercised owner, substitute and approver flows
using synthetic local IAM. These are previously recorded runs; adding these
records does not rerun or extend their validation.

## Configuration and limits

Production use requires approved HR policies, hierarchy/profile data, published
calendars and live institution IAM. External HR/calendar feeds and institute SSO
were not verified. Year-end automation fails closed until its boundary is
configured. See the evidence document for detailed limitations.
