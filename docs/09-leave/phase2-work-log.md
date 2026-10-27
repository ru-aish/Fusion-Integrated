# Act: Phase 2 implementation, review and verification log

This log records the work after the preserved Phase-1 commit
`2fe48eebab445955efb596a012b7ec96ecd0d9f4`. Prompts below are concise summaries
of recorded task instructions, not verbatim transcripts or invented independent
model runs. Each implementation entry points to its actual resulting commit.
No per-model inference timing was measured.

The implementation, review and QA work used Luna agents at medium reasoning;
standard speed was used after that preference was specified. The user-stated
model choice is `Qwen 3.8, 27B, Q3_K_M`; execution with that model is not verified
and is not claimed here. The original selected local GPT-OSS runtime was
unavailable. See [the evidence and limitations](phase2-evidence.md).

## Starting point and preservation

Phase 1 supplied a pending-request submission/list/balance pilot. Its commit is
preserved as `phase1-elm-pr78` and in a verified separate Git bundle. The complete
ELM specification package was retained outside the application tree. The
[Phase-1 prompt bundles](phase1-prompt-bundles.md) describe logical groups within
its single commit; they are not additional historical commits.

## 1. Validate the inherited pilot against the specification

**Prompt summary**

```text
Preserve the Phase-1 implementation. Read the complete ELM specifications,
inspect the pilot and Fusion integration, map gaps, improve material defects,
and add meaningful regression tests. Build the application and record actual
verification results and unresolved requirements.
```

**Resulting commit:**
[`7fcc21cee7fb7f18ce239424d447993e33c8f33a`](https://github.com/ru-aish/Fusion-Integrated/commit/7fcc21cee7fb7f18ce239424d447993e33c8f33a)
— Improve ELM request validation and traceability.

Added half-day and Station Leave fields, category-aware counting, overlap and
balance validation, tests, client controls, migration and evidence documentation.
This was a partial improvement, not full specification completion.

**Verification and findings:** the first pass reported passing static/build/client
checks and three pure counting tests. API tests were blocked by unavailable
PostgreSQL. An independent review found that category-specific account locks did
not prevent employee-wide overlaps across concurrent leave categories.

## 2. Implement workflows and correct employee-wide serialization

**Prompt summary**

```text
Fix the cross-category overlap race using employee-scoped serialization and
PostgreSQL concurrency tests. Implement coherent approval routing, substitute
consent, assigned tasks, history, withdrawal, cancellation, extension and
resumption, with auditable accounting effects and usable frontend controls.
Test negative permissions, terminal outcomes and failure paths.
```

**Resulting commit:**
[`39766a07dae197b45dc07886d5433cd299724a8c`](https://github.com/ru-aish/Fusion-Integrated/commit/39766a07dae197b45dc07886d5433cd299724a8c)
— Improve ELM Phase 2 workflows and validation.

Added profile/policy/calendar inputs, employee-wide locking, substitute and
multi-level authority workflows, assigned inbox/history, ledger lifecycle events,
and cancellation/extension/resumption flows. Added COL evidence input and atomic
calendar replacement. The work included recovery of preserved uncommitted files
from an interrupted implementation pass.

**Verification and findings:** 41 PostgreSQL leave/IAM tests and 36 frontend tests
passed; clean and populated Phase-1 migrations were checked. An early environment
run overlapped in-progress schema changes and was explicitly excluded as a clean
baseline. Fresh review found missing substitute availability/self-nomination
checks, substitute access to medical evidence references and stale OpenAPI fields
and endpoints. Browser login initially failed because the external IAM service
was unreachable.

## 3. Complete accounts, operations and administrative interfaces

**Prompt summary**

```text
Implement authoritative year-scoped accounts and reconciliation, annual issuance
and idempotent year-end processing, offline-sanction synchronization, SLA
reminders/escalation, scoped exports and configuration/import screens. Correct
substitute eligibility and private-field exposure and regenerate the API and
permission contracts. Use an isolated synthetic IAM for runtime checks when
institution IAM is unavailable, and disclose that distinction.
```

**Resulting commit:**
[`58a4c43887aa4b4301497fbe0405dd4a74551e9b`](https://github.com/ru-aish/Fusion-Integrated/commit/58a4c43887aa4b4301497fbe0405dd4a74551e9b)
— Complete Fusion ELM Phase 2 account and admin flows.

Added annual accounts/credits/adjustments, legacy reconciliation, year-end runs,
offline imports, SLA processing, history/export/print controls, admin screens,
substitute checks, privacy scoping and regenerated contracts.

**Verification and findings:** 55 backend/IAM tests and 38 frontend tests passed,
with clean, Phase-1 and pre-account lifecycle migration checks. Independent QA
reproduced year-close refunds stranded in closed accounts during pending
cancellation/resumption. Browser QA found substitute acceptance advanced the
state without creating the next approver task. It also found the declared client
lint command lacked its tool/configuration. Review identified the unconfigured,
hardcoded year-end trigger. Passing existing suites did not resolve these defects.

## 4. Fix independently reproduced failures and verify again

**Prompt summary**

```text
Fix year-close behavior for all pending balance-changing workflows and prevent
silent mutations of closed-year accounts. Make substitute acceptance create the
next assigned task atomically. Configure the year-end run boundary and fail
closed until it is supplied, while retaining calendar-year entitlements. Repair
the client lint toolchain, add regressions for the independent reproducers, and
verify the complete runtime approval path plus balances, history and export.
```

**Resulting commit:**
[`ed91cd0a39c6c00c90d59844a3e960ba178feb71`](https://github.com/ru-aish/Fusion-Integrated/commit/ed91cd0a39c6c00c90d59844a3e960ba178feb71)
— fix leave year close and substitute routing.

Year close now defers the entire run when an affected account has a pending
balance-changing workflow; closed-year changes are rejected pending audited
reconciliation. Substitute acceptance assigns the next task in the transaction.
The year-end trigger is configurable and inactive until configured. The lint
command now has a working toolchain and configuration.

**Verification:** 63 PostgreSQL backend/IAM tests and 38 frontend tests passed.
Typecheck, build, ESLint, Django checks, migration drift, generated OpenAPI
comparison, permissions/navigation/module-boundary checks and focused Ruff passed.
The browser flow completed owner submission, substitute acceptance and Unit Head
approval, with balance/history/export confirmation under synthetic local IAM.

## 5. Final independent review and handoff

A new read-only reviewer inspected the final candidate and prior findings,
reran seven focused PostgreSQL regressions and relevant schema/drift/lint checks,
and reported no qualifying correctness findings. At that review, a read-only
merge-tree check against upstream `main` at `02b01fe` found no conflicts. This is
local verification, not a claim that remote CI or institute SSO passed.

The checkout was clean at `ed91cd0`; Phase-1 and Phase-2 bundles were verified.
Task-owned dev/IAM services and the isolated test database were stopped, with
reproduction data retained. This documentation commit adds the log and supplied
Phase-1 prompt-bundle file without changing the tested application code.

## Remaining configuration and limitations

- Approved HR/hierarchy/policy data, published calendars and live IAM are required
  before production operation. Runtime browser tests used synthetic IAM.
- Year-end automation fails closed until HR supplies the trigger boundary.
- ESLint reported 40 warnings and no errors; the build retained a 502.53 kB
  main-chunk advisory.
- No run with the unavailable original local model or the stated Qwen choice is
  claimed. These records do not replace actual local-model execution logs.

Detailed command outcomes and requirement references are in
[phase2-evidence.md](phase2-evidence.md).
