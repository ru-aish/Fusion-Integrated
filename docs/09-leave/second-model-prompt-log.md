# Second implementation — two-prompt reconstruction

**PR:** [Employee Leave Management workflow module — #1](https://github.com/ru-aish/Fusion-Integrated/pull/1)
**Final commit:** [`69438ee40a4f0907d4012602297e8d35a5b4fc80`](https://github.com/ru-aish/Fusion-Integrated/commit/69438ee40a4f0907d4012602297e8d35a5b4fc80)
**Final diff:** 45 files; 5,060 additions; 7 deletions.

These two prompts reconstruct the broad implementation and smaller hardening
scope visible in the final code and PR description. They are not recovered
verbatim prompts or proof of two separate executions. The PR has one commit;
there is no separately preserved intermediate diff or commit for either prompt.
Model execution time and per-prompt change counts were not measured.

## Prompt 1 — broad implementation

```text
Work in an isolated checkout of the supplied Fusion Base repository. Read the
Assignment 6 instructions, complete Employee Leave Management specifications,
workflow/state-transition tables, business rules, use cases and traceability
matrix, together with Fusion's setup, IAM and module guides. Inspect existing
modules and implement the ELM module using the established conventions.

Build a coherent backend and frontend for employee leave applications and
balances, substitute responses and approval tasks, Unit Head decisions,
Establishment routing and final sanction. Include withdrawal, cancellation,
extension and resumption records. Represent workflow transitions explicitly and
record decisions and balance transactions. Include policy and authority-route
configuration, holiday calendar publication, offline records/corrections,
annual credits and year-end processing, notifications and SLA jobs where the
supplied specification calls for them.

Integrate models and migrations, permission and module registration, API routes,
OpenAPI contracts, navigation, the existing login/role system and frontend HTTP
client. Provide employee application/list/balance/task/resumption pages and
administration screens. Use configured institution data and provider contracts;
do not invent external calendar or attendance integrations. Explain unavailable
dependencies and incomplete behavior in the implementation blueprint.

Keep changes within this module and the required integration points. Reuse
existing infrastructure. Check startup, migrations, frontend typechecking and a
small synthetic-account request/approval flow. Exercise valid requests, reversed
dates, half-day CL, holiday counting, insufficient balances, wrong actors and
missing permissions. Report observed results separately from untested cases.
```

**Corresponding changes in the final commit:**

- Added the workflow/domain, models, initial migration, selectors, services and API.
- Added six employee/admin pages, typed API hooks and state indicators.
- Added accounts, authority/policy/calendar administration, cancellation,
  extension, resumption, scheduled work and notifications.
- Added module/navigation/permission/schema integration and the implementation
  blueprint. These are implemented code paths, not evidence that every requirement
  or edge case passed runtime validation.

## Prompt 2 — focused hardening

```text
Review the new ELM module without rewriting its architecture or expanding its
scope. Concentrate on approval consistency and malformed API inputs. Make the
workflow transition reload and lock the current application row inside the
transaction. Before final approval or extension posting, lock/recheck the
available balance and reject an insufficient balance without partially saving
the decision or debit. Ensure a non-numeric balance-year query produces a clear
validation error rather than an unhandled server error.

Check that assigned-actor and permission checks remain enforced and that invalid
or repeated workflow actions cannot silently repeat a transition. Verify valid
requests still reach their intended approval state. Run startup/migration and
frontend checks where available, and a small synthetic login/request/approval
smoke test. Also try an invalid year and insufficient-balance sanction; report
exactly which checks ran and any limitations. Keep the correction small and
preserve unrelated work.
```

**Hardening present in the same final commit:**

- `_transition` reloads the application with `select_for_update()`; public mutation
  service entry points use atomic transactions.
- Approval/extension obtains a locked balance and rejects insufficient funds
  before saving the final state and posting the debit.
- `BalanceView` catches invalid year conversion and raises a validation error.

These observations establish that safeguards exist in the source. They do not
establish concurrent-request correctness or passing API regressions.

## Validation summary

**New retrospective checks: 11 passed on 27 October 2026.** The checks loaded the
unchanged pure counting and workflow modules directly from the final commit:

1. EL counts the entire Friday–Monday interval, including the weekend.
2. CL excludes the weekend from the same interval.
3. CL excludes an explicitly configured holiday.
4. Single-day half CL counts as 0.5.
5. Single-date RH counts as one day.
6. Reversed dates raise a validation exception in the counting function.
7. Submission requiring a substitute routes to the substitute state.
8. Non-Director substitute acceptance routes to Unit Head review.
9. Unit Head CL/RH approval resolves to approved.
10. Extension sanction resolves to the completed extension state.
11. An invalid submission from an already approved state is rejected.

Command: `/work/bin/workspace-run check -- python /work/artifacts/fusion-elm-second-model/validate_domain.py`.
The script is retained locally outside the PR. It checks pure functions only;
it does not test permission enforcement, persistence, transactions or UI behavior.
No application files or PR commits were changed for this verification.

**Earlier reported verification:** the PR description records startup,
migrations, frontend typechecking and a brief synthetic-account
login/request/approval flow. Those checks were not rerun here; the PR explicitly
says full suites and visual browser verification were not run.

**Proposed checks, not executed:** malformed `year` should return a validation
error; insufficient-balance sanction should roll back; unauthorized actors should
be denied; concurrent actions should not duplicate decisions/debits. These are
expected outcomes to test, not passing results. External calendar and attendance
adapters remain prerequisites for their applicable flows.
