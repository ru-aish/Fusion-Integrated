# Employee Leave Management — Phase 2

The inherited Phase 1 pilot lets an employee submit a pending leave request, list
their own requests, and view their own leave balances. Phase 2 adds server-side
validation for date order, CL half-days, overlap, available balance, and Station
Leave details. It uses the existing Fusion login, role switcher, HTTP client and
application shell.

The client pages are `/leave/requests` and `/leave/balances`. The API endpoints are
`/api/v1/leave/requests/` and `/api/v1/leave/balances/`. The module grant and
fine-grained permission are checked by the API. Ownership comes from the authenticated
IAM Principal; clients cannot set employee ID or initial status; update/delete remain
disabled.

## Phase 2 traceability and known scope

| Requirement area | Phase 2 result | Evidence / limitation |
|---|---|---|
| Employee ownership and access | Retained from Phase 1 | Principal-derived owner; read querysets remain own-only; create permission tested |
| Date order | Implemented | Invalid end-before-start rejected |
| CL first/second half | Implemented | One-day CL only; 0.5 day commitment and opposite halves may share a date |
| Category day counting | Partial | EL/COL/VL count continuous dates; CL/SCL/RH skip weekends. Institute closed holidays are not integrated. |
| Active-request overlap | Implemented | Pending/approved intersections rejected except opposite CL halves |
| Available balance | Implemented | Requires a provisioned category balance; commitments counted; row lock/recheck serializes submissions |
| Station Leave coupling | Partial | Captured on same request, details required when enabled; no geographical validation |
| Annual entitlement and lapse/carry-forward | Not implemented | Requires policy/year accounting and event processing |
| RH and VL calendar applicability | Not implemented | Published RH and external Academic Calendar integrations absent |
| Substitute eligibility/consent | Not implemented | No substitute directory responsibility model or consent workflow |
| Unit Head / Establishment / final authority routing | Not implemented | No hierarchy configuration or approval tasks |
| Withdraw, cancel, extend, resume | Not implemented | No corresponding state transitions or endpoints |
| Approval accounting, ledger, offline sync, year-end, SLA | Not implemented | No transactions ledger, scheduled processing, or task notification system |
| Export/print and request history | Partial | List view only; no print/export or decision history |

This is a focused improvement of the inherited pilot, not a complete or deployment-
ready ELM module. It must not be presented as supporting final approvals or reliable
leave-account posting. Those require the complete authority hierarchy, effective
calendar sources, and transaction-ledger/workflow design in the synchronized specs.

## Baseline and provenance

The exact Phase 1 PR head is `2fe48eebab445955efb596a012b7ec96ecd0d9f4`.
It is preserved in local Git tag `phase1-elm-pr78` and bundle
`/work/Code/fusion-elm-phase1-pr78.bundle`. The supplied specification package is
retained in `/work/Code/Fusion-ELM-Phase2-Inputs/` (copied intact from the experiment
input package; 17 files, 2.4 MiB).
The Phase 2 branch is based directly on that PR head; remote history was not changed.

## Verification

See [Phase 2 evidence](phase2-evidence.md) for commands, results, environment
limitations, and the local-model availability record.
