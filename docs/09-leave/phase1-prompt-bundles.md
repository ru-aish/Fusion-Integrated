# Phase 1 — Change-bundled prompt sequence

Reconstructed prompt sequence derived from the final code diff. It describes logical change bundles, not a recovered sequence of historical prompts or separate executions. All bundles are contained in one recorded final commit; intermediate commits and per-bundle timings are not available.

**Final commit:** `2fe48eebab445955efb596a012b7ec96ecd0d9f4`
**Total:** 19 changed files; 629 added lines; 0 deleted lines.

## Prompt 1 — Initial module and backend scaffold

```text
Read the supplied Assignment 6 instructions, complete ELM specification
package and the Fusion Base documentation. Inspect the project structure,
reference modules, IAM interfaces and frontend integration conventions.

Start the initial ELM pilot in the assigned working checkout. Establish the
leave module, leave-category choices, request and balance data models,
application registration and API routes. The request model should capture
employee identity, category, dates, reason, pending status and timestamps;
the balance model should keep one employee/category balance record.
Preserve Fusion's existing architecture. Report specification features
that remain outside this initial pilot.
```

**Change bundle:** 6 files, 57 added lines, 0 deleted lines.

**Files:** `modules/leave/__init__.py`, `modules/leave/apps.py`, `modules/leave/models.py`, `modules/leave/api/urls.py`, `config/settings/base.py`, `config/urls.py`.

**Commit containing this bundle:** `2fe48ee` (same consolidated final commit).

## Prompt 2 — Fix permissions, ownership and request validation

```text
Review the pilot's request and balance endpoints against Fusion's IAM and
permission conventions. Scope both querysets to the authenticated Principal.
Take employee identity from the server, make ownership/status fields
read-only, and prevent update/delete of submitted requests. Require the
module grant and distinct viewing/creation permissions. Reject reversed
date ranges. Declare module navigation, permissions and employee/HR grants
consistently so the shell and API agree.
```

**Change bundle:** 3 files, 87 added lines, 0 deleted lines.

**Files:** `modules/leave/api/views.py`, `modules/leave/serializers.py`, `modules/leave/registry.py`.

**Commit containing this bundle:** `2fe48ee` (same consolidated final commit).

## Prompt 3 — Complete database integration

```text
Generate the initial database migration for the request and balance models,
including the employee/category balance uniqueness constraint. Ensure the
migration package is discoverable, apply it to an isolated development
database and check that model definitions and migrations are consistent.
```

**Change bundle:** 2 files, 41 added lines, 0 deleted lines.

**Files:** `modules/leave/migrations/__init__.py`, `modules/leave/migrations/0001_initial.py`.

**Commit containing this bundle:** `2fe48ee` (same consolidated final commit).

## Prompt 4 — Replace placeholder client screens with usable flows

```text
Connect the leave module to Fusion's client registry and lazy-loaded routes.
Implement request submission with leave type, dates and reason; show the
employee's request list and status. Implement a balance list with category,
available balance and update date. Use the shared authenticated HTTP client,
unwrap paginated API results, show loading/error states, disable duplicate
submission while a request is pending, and refresh requests after creation.
```

**Change bundle:** 4 files, 107 added lines, 0 deleted lines.

**Files:** `client/src/app/registry.ts`, `client/src/modules/leave/routes.tsx`, `client/src/modules/leave/pages/RequestsPage.tsx`, `client/src/modules/leave/pages/BalancesPage.tsx`.

**Commit containing this bundle:** `2fe48ee` (same consolidated final commit).

## Prompt 5 — Synchronize generated artifacts and document the final pilot

```text
Regenerate the permission manifest, permission catalogue and OpenAPI schema
from the pilot implementation. Resolve schema-generation and integration
check failures. Check Django startup, migration consistency, permissions,
module boundaries, navigation/routes, frontend typechecking and build, and
perform a brief synthetic-account request/list/balance isolation smoke test.
Document setup, endpoints, working scope, actual verification and limitations.
Do not claim approvals, balance accounting, substitute routing, detailed
category rules, scheduled work or a complete ELM implementation if absent.
```

**Change bundle:** 4 files, 337 added lines, 0 deleted lines.

**Files:** `registry/permissions.json`, `docs/02-iam/permission-catalog.generated.md`, `openapi/fusion-integrated.v1.yaml`, `docs/09-leave/README.md`.

**Commit containing this bundle:** `2fe48ee` (same consolidated final commit).
