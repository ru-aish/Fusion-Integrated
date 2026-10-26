from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from conftest import make_session
from modules.leave.models import (
    LeaveBalance,
    LeaveEmployeeProfile,
    LeaveLedgerEntry,
    LeavePolicy,
    LeaveRequest,
    LeaveSLAConfig,
    LeaveSLAEvent,
    LeaveTask,
    LeaveYearAccount,
    LeaveYearRun,
)
from modules.leave.services import issue_entitlements, process_sla, run_year_end

pytestmark = pytest.mark.django_db


def client(stub_iam, user_id, permissions):
    stub_iam(
        make_session(
            user_id=user_id,
            kind="staff",
            roles=("hr",),
            active_role="hr",
            modules=("leave_cell",),
            permissions=permissions,
        )
    )
    result = APIClient()
    result.credentials(HTTP_AUTHORIZATION="Token test")
    return result


def test_initial_substitute_self_and_conflicting_leave_are_rejected(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveBalance.objects.create(employee_id="1001", leave_type="CL", balance=8)
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001",
        defaults={
            "unit_head_id": "2001",
            "sanctioning_authority_id": "3001",
            "substitute_required": True,
            "eligible_substitute_ids": ["1001", "4001"],
        },
    )
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4001", defaults={})
    LeaveRequest.objects.create(
        employee_id="4001",
        leave_type="EL",
        start_date="2026-11-02",
        end_date="2026-11-02",
        workflow_state="approved",
    )
    api = client(stub_iam, 1001, ("leave_cell.requests.create",))
    body = {
        "leave_type": "CL",
        "start_date": "2026-11-02",
        "end_date": "2026-11-02",
        "reason": "x",
        "substitute_id": "1001",
    }
    assert api.post("/api/v1/leave/requests/", body, format="json").status_code == 400
    body["substitute_id"] = "4001"
    assert api.post("/api/v1/leave/requests/", body, format="json").status_code == 400


def test_annual_cap_applies_across_separate_requests_and_account_rows(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    LeaveYearAccount.objects.create(
        employee_id="1001", leave_type="CL", year=2026, opening_balance=8, available_balance=8
    )
    api = client(stub_iam, 1001, ("leave_cell.requests.create",))
    first = api.post(
        "/api/v1/leave/requests/",
        {"leave_type": "CL", "start_date": "2026-11-02", "end_date": "2026-11-05", "reason": "x"},
        format="json",
    )
    assert first.status_code == 201
    second = api.post(
        "/api/v1/leave/requests/",
        {"leave_type": "CL", "start_date": "2026-11-09", "end_date": "2026-11-12", "reason": "x"},
        format="json",
    )
    assert second.status_code == 201
    third = api.post(
        "/api/v1/leave/requests/",
        {"leave_type": "CL", "start_date": "2026-11-16", "end_date": "2026-11-16", "reason": "x"},
        format="json",
    )
    assert third.status_code == 400


def test_cross_year_request_splits_reservations_and_debits_by_account(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    for year in (2026, 2027):
        LeaveYearAccount.objects.create(
            employee_id="1001", leave_type="EL", year=year, opening_balance=1, available_balance=1
        )
    api = client(stub_iam, 1001, ("leave_cell.requests.create",))
    response = api.post(
        "/api/v1/leave/requests/",
        {"leave_type": "EL", "start_date": "2026-12-31", "end_date": "2027-01-01", "reason": "x"},
        format="json",
    )
    assert response.status_code == 201
    request_id = response.json()["id"]
    assert set(
        LeaveLedgerEntry.objects.filter(request_id=request_id, kind="reserve").values_list(
            "year", flat=True
        )
    ) == {2026, 2027}
    unit = client(stub_iam, 2001, ("leave_cell.tasks.act",))
    assert (
        unit.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "recommend"}, format="json"
        ).status_code
        == 200
    )
    authority = client(stub_iam, 3001, ("leave_cell.tasks.act",))
    assert (
        authority.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
        ).status_code
        == 200
    )
    assert set(
        LeaveLedgerEntry.objects.filter(request_id=request_id, kind="debit").values_list(
            "year", flat=True
        )
    ) == {2026, 2027}
    assert all(
        x.available_balance == 0
        for x in LeaveYearAccount.objects.filter(
            employee_id="1001", leave_type="EL", year__in=(2026, 2027)
        )
    )
    for account in LeaveYearAccount.objects.filter(
        employee_id="1001", leave_type="EL", year__in=(2026, 2027)
    ):
        ledger_net = sum(
            LeaveLedgerEntry.objects.filter(
                employee_id="1001", leave_type="EL", year=account.year
            ).values_list("amount", flat=True),
            Decimal("0"),
        )
        assert account.opening_balance + ledger_net == account.available_balance


def test_substitute_response_omits_medical_reference(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001",
        defaults={
            "unit_head_id": "2001",
            "sanctioning_authority_id": "3001",
            "eligible_substitute_ids": ["4001"],
        },
    )
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4001", defaults={})
    LeaveBalance.objects.create(employee_id="1001", leave_type="COL", balance=10)
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    created = applicant.post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "COL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "reason": "care",
            "medical_evidence_reference": "MED-PRIVATE",
            "substitute_id": "4001",
        },
        format="json",
    )
    assert created.status_code == 201
    substitute = client(stub_iam, 4001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
    assigned = substitute.get(f"/api/v1/leave/requests/{created.json()['id']}/?scope=assigned")
    assert assigned.status_code == 200
    assert "medical_evidence_reference" not in assigned.json()
    assert "reason" not in assigned.json()
    assigned_list = substitute.get("/api/v1/leave/requests/?scope=assigned")
    listed = assigned_list.json()["results"][0]
    assert "medical_evidence_reference" not in listed
    assert "reason" not in listed
    export = substitute.get(f"/api/v1/leave/requests/{created.json()['id']}/export/")
    assert export.status_code == 200
    assert "reason" not in export.json()
    assert "medical_evidence_reference" not in export.json()
    action = substitute.post(
        f"/api/v1/leave/requests/{created.json()['id']}/act/",
        {"action": "decline", "note": "substitute private reason"},
        format="json",
    )
    assert action.status_code == 200 and "medical_evidence_reference" not in action.json()
    history = substitute.get(f"/api/v1/leave/requests/{created.json()['id']}/history/")
    assert history.status_code == 200
    assert all("note" not in event for event in history.json())
    export = substitute.get(f"/api/v1/leave/requests/{created.json()['id']}/export/")
    assert all("note" not in event for event in export.json()["decision_history"])


def test_request_owner_can_read_history_and_export_with_owner_permission(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    LeaveBalance.objects.create(employee_id="1001", leave_type="CL", balance=8)
    owner = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.requests.view"))
    created = owner.post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "reason": "owner",
        },
        format="json",
    )
    request_id = created.json()["id"]
    assert owner.get(f"/api/v1/leave/requests/{request_id}/history/").status_code == 200
    exported = owner.get(f"/api/v1/leave/requests/{request_id}/export/")
    assert exported.status_code == 200 and exported.json()["reason"] == "owner"


def test_substitute_availability_is_rechecked_on_acceptance_and_replacement(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001",
        defaults={
            "unit_head_id": "2001",
            "sanctioning_authority_id": "3001",
            "eligible_substitute_ids": ["4001", "4002"],
        },
    )
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4001", defaults={})
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4002", defaults={})
    LeaveBalance.objects.create(employee_id="1001", leave_type="CL", balance=8)
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    created = applicant.post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "CL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "reason": "x",
            "substitute_id": "4001",
        },
        format="json",
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    LeaveRequest.objects.create(
        employee_id="4001",
        leave_type="EL",
        start_date="2026-11-02",
        end_date="2026-11-02",
        workflow_state="approved",
    )
    accept = client(stub_iam, 4001, ("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "accept"}, format="json"
    )
    assert accept.status_code == 400
    assert LeaveTask.objects.filter(request_id=request_id, role="substitute", state="open").exists()

    decline = client(stub_iam, 4001, ("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "decline"}, format="json"
    )
    assert decline.status_code == 200
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    self_replace = applicant.post(
        f"/api/v1/leave/requests/{request_id}/act/",
        {"action": "replace_substitute", "substitute_id": "1001"},
        format="json",
    )
    assert self_replace.status_code == 400
    LeaveRequest.objects.create(
        employee_id="4002",
        leave_type="EL",
        start_date="2026-11-02",
        end_date="2026-11-02",
        workflow_state="approved",
    )
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    replace = applicant.post(
        f"/api/v1/leave/requests/{request_id}/act/",
        {"action": "replace_substitute", "substitute_id": "4002"},
        format="json",
    )
    assert replace.status_code == 400


def test_offline_record_replay_conflict_and_authority_validation(stub_iam):
    from modules.leave.models import LeaveOfflineRecord

    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    LeaveBalance.objects.create(employee_id="1001", leave_type="CL", balance=8)
    LeaveYearAccount.objects.create(
        employee_id="1001",
        leave_type="CL",
        year=2026,
        opening_balance=8,
        available_balance=8,
        source="legacy_snapshot",
    )
    api = client(stub_iam, 9000, ("leave_cell.offline.sync",))
    body = {
        "external_id": "paper-9",
        "employee_id": "1001",
        "leave_type": "CL",
        "start_date": "2026-11-02",
        "end_date": "2026-11-02",
        "reason": "personal",
        "sanction_reference": "ORD-9",
        "authority_id": "2001",
        "source_reason": "network outage",
    }
    denied = {**body, "external_id": "bad", "authority_id": "9999"}
    assert api.post("/api/v1/leave/offline-records/", denied, format="json").status_code == 400
    first = api.post("/api/v1/leave/offline-records/", body, format="json")
    assert first.status_code == 201 and first.json()["created"] is True
    replay = api.post("/api/v1/leave/offline-records/", body, format="json")
    assert replay.status_code == 200 and replay.json()["created"] is False
    assert LeaveOfflineRecord.objects.count() == 1
    assert LeaveYearAccount.objects.get(
        employee_id="1001", leave_type="CL", year=2026
    ).available_balance == Decimal("7.00")
    assert (
        LeaveLedgerEntry.objects.filter(
            employee_id="1001", leave_type="CL", year=2026, kind="debit", amount=-1
        ).count()
        == 1
    )
    conflict = {**body, "reason": "different"}
    assert api.post("/api/v1/leave/offline-records/", conflict, format="json").status_code == 400
    assert LeaveRequest.objects.get(pk=first.json()["request_id"]).workflow_state == "approved"
    assert not LeaveTask.objects.filter(request_id=first.json()["request_id"]).exists()


def test_offline_import_denial_and_failed_posting_leave_no_partial_records(stub_iam):
    from modules.leave.models import LeaveOfflineRecord

    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    LeaveBalance.objects.create(employee_id="1001", leave_type="CL", balance=0)
    LeaveYearAccount.objects.create(
        employee_id="1001", leave_type="CL", year=2026, opening_balance=0, available_balance=0
    )
    payload = {
        "external_id": "paper-insufficient",
        "employee_id": "1001",
        "leave_type": "CL",
        "start_date": "2026-11-02",
        "end_date": "2026-11-02",
        "reason": "personal",
        "sanction_reference": "ORD-10",
        "authority_id": "2001",
        "source_reason": "outage",
    }
    denied = client(stub_iam, 9000, ())
    assert denied.post("/api/v1/leave/offline-records/", payload, format="json").status_code == 403
    admin = client(stub_iam, 9000, ("leave_cell.offline.sync",))
    assert admin.post("/api/v1/leave/offline-records/", payload, format="json").status_code == 400
    assert LeaveOfflineRecord.objects.count() == 0
    assert not LeaveRequest.objects.filter(employee_id="1001").exists()
    assert LeaveLedgerEntry.objects.count() == 0


def test_entitlement_issue_and_year_end_are_idempotent_and_preserve_carryover():
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(employee_id="f1", defaults={"is_faculty": True})
    LeaveEmployeeProfile.objects.update_or_create(employee_id="n1", defaults={"is_faculty": False})
    issue_entitlements(2026, "admin")
    issue_entitlements(2026, "admin")
    assert (
        LeaveYearAccount.objects.get(employee_id="n1", leave_type="CL", year=2026).available_balance
        == 8
    )
    vl = LeaveYearAccount.objects.get(employee_id="f1", leave_type="VL", year=2026)
    vl.available_balance = Decimal("5.5")
    vl.save()
    el = LeaveYearAccount.objects.get(employee_id="n1", leave_type="EL", year=2026)
    el.available_balance = Decimal("7")
    el.save()
    run_year_end(2026, "admin")
    run_year_end(2026, "admin")
    assert LeaveYearRun.objects.filter(year=2026).count() == 1
    for category, amount in (("CL", 8), ("RH", 2), ("SCL", 15)):
        old = LeaveYearAccount.objects.get(employee_id="n1", leave_type=category, year=2026)
        assert old.available_balance == 0
        assert LeaveLedgerEntry.objects.filter(
            employee_id="n1", leave_type=category, year=2026, kind="lapse", amount=-amount
        ).exists()
    assert (
        LeaveYearAccount.objects.get(employee_id="f1", leave_type="VL", year=2026).available_balance
        == 0
    )
    assert LeaveYearAccount.objects.get(
        employee_id="f1", leave_type="EL", year=2027
    ).available_balance == Decimal("2.75")
    assert LeaveYearAccount.objects.get(
        employee_id="n1", leave_type="EL", year=2027
    ).available_balance == Decimal("37")
    assert LeaveYearAccount.objects.get(
        employee_id="n1", leave_type="COL", year=2027
    ).available_balance == Decimal("40")


def test_employee_accounts_expose_year_transactions_and_reconciliation_only_for_owner(stub_iam):
    LeaveYearAccount.objects.create(
        employee_id="1001", leave_type="CL", year=2026, opening_balance=0, available_balance=8
    )
    LeaveLedgerEntry.objects.create(
        employee_id="1001",
        leave_type="CL",
        year=2026,
        amount=8,
        kind="credit",
        reference="annual entitlement",
        actor_id="admin",
    )
    LeaveYearAccount.objects.create(
        employee_id="1002", leave_type="CL", year=2026, opening_balance=0, available_balance=8
    )
    response = client(stub_iam, 1001, ("leave_cell.balances.view",)).get("/api/v1/leave/accounts/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["reconciled"] is True
    assert Decimal(str(response.json()[0]["ledger_balance"])) == Decimal("8.00")
    assert response.json()[0]["transactions"][0]["kind"] == "credit"


def test_admin_opening_credit_and_adjustment_require_audited_authorization(stub_iam):
    LeaveEmployeeProfile.objects.create(employee_id="new-account")
    body = {
        "employee_id": "new-account",
        "leave_type": "CL",
        "year": 2026,
        "amount": "3.00",
        "reason": "HR entitlement correction order 11",
    }
    denied = client(stub_iam, 9000, ())
    assert (
        denied.post("/api/v1/leave/year-end/accounts/adjust/", body, format="json").status_code
        == 403
    )
    admin = client(stub_iam, 9000, ("leave_cell.accounts.manage",))
    posted = admin.post("/api/v1/leave/year-end/accounts/adjust/", body, format="json")
    assert posted.status_code == 200
    account = LeaveYearAccount.objects.get(employee_id="new-account", leave_type="CL", year=2026)
    assert account.opening_balance == 0 and account.available_balance == Decimal("3.00")
    credit = LeaveLedgerEntry.objects.get(employee_id="new-account")
    assert credit.kind == "credit" and credit.reference == body["reason"]
    next_adjustment = admin.post(
        "/api/v1/leave/year-end/accounts/adjust/",
        {**body, "amount": "1.00", "reason": "Approved correction"},
        format="json",
    )
    assert next_adjustment.status_code == 200
    assert (
        LeaveLedgerEntry.objects.filter(employee_id="new-account", kind="adjustment").count() == 1
    )


def test_admin_cannot_adjust_a_closed_calendar_account(stub_iam):
    LeaveEmployeeProfile.objects.create(employee_id="closed-adjustment")
    LeaveYearAccount.objects.create(
        employee_id="closed-adjustment", leave_type="CL", year=2026,
        opening_balance=8, available_balance=8,
    )
    run_year_end(2026, "admin")
    admin = client(stub_iam, 9000, ("leave_cell.accounts.manage",))
    response = admin.post(
        "/api/v1/leave/year-end/accounts/adjust/",
        {
            "employee_id": "closed-adjustment", "leave_type": "CL", "year": 2026,
            "amount": "1.00", "reason": "must be rejected after close",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "closed calendar years" in str(response.json()).lower()


def test_year_end_exceptions_can_be_replayed_after_pending_commitment_resolves():
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.create(employee_id="pending-close")
    issue_entitlements(2026, "admin")
    request = LeaveRequest.objects.create(
        employee_id="pending-close",
        leave_type="CL",
        start_date="2026-12-30",
        end_date="2026-12-30",
        workflow_state="awaiting_unit_head",
    )
    first = run_year_end(2026, "admin")
    assert first.exceptions == [
        {
            "employee_id": "pending-close",
            "leave_type": "CL",
            "reason": "pending requests remain at year end",
        }
    ]
    request.workflow_state = "withdrawn"
    request.save(update_fields=["workflow_state"])
    run_year_end(2026, "admin")
    account = LeaveYearAccount.objects.get(employee_id="pending-close", leave_type="CL", year=2026)
    assert account.available_balance == 0
    assert not LeaveYearRun.objects.get(year=2026).exceptions


def test_scheduled_calendar_close_catches_up_and_is_idempotent():
    from modules.leave.tasks import process_year_end_boundary

    LeavePolicy.objects.update_or_create(key="current", defaults={"year_end_month": 1, "year_end_day": 1})
    LeaveEmployeeProfile.objects.create(employee_id="boundary-worker")
    assert process_year_end_boundary("2027-01-02")["processed"] is True
    assert LeaveYearRun.objects.filter(year=2026, exceptions=[]).exists()
    assert process_year_end_boundary("2027-02-01")["processed"] is False
    assert LeaveYearAccount.objects.filter(
        employee_id="boundary-worker", leave_type="CL", year=2027, available_balance=8
    ).exists()


def test_substitute_acceptance_creates_actionable_next_task_and_routes_all_categories(stub_iam):
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001",
        defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001", "eligible_substitute_ids": ["4001"]},
    )
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4001", defaults={})
    for category, balance in (("CL", 8), ("EL", 30)):
        LeaveYearAccount.objects.update_or_create(
            employee_id="1001", leave_type=category, year=2026,
            defaults={"opening_balance": balance, "available_balance": balance},
        )
    for category, decision in (("CL", "approve"), ("EL", "recommend")):
        api = client(stub_iam, 1001, ("leave_cell.requests.create",))
        request_day = "2026-11-02" if category == "CL" else "2026-11-03"
        created = api.post("/api/v1/leave/requests/", {
            "leave_type": category, "start_date": request_day, "end_date": request_day,
            "reason": "routing regression", "substitute_id": "4001",
        }, format="json")
        assert created.status_code == 201, created.content
        request_id = created.json()["id"]
        sub = client(stub_iam, 4001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
        assert sub.get("/api/v1/leave/inbox/").status_code == 200
        assert sub.post(f"/api/v1/leave/requests/{request_id}/act/", {"action": "accept"}, format="json").status_code == 200
        unit = client(stub_iam, 2001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
        inbox = unit.get("/api/v1/leave/inbox/")
        assert inbox.status_code == 200
        assert any(row["request_id"] == request_id and row["role"] == "unit_head" for row in inbox.json())
        sub = client(stub_iam, 4001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
        assert sub.post(f"/api/v1/leave/requests/{request_id}/act/", {"action": decision}, format="json").status_code == 403
        unit = client(stub_iam, 2001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
        acted = unit.post(f"/api/v1/leave/requests/{request_id}/act/", {"action": decision}, format="json")
        assert acted.status_code == 200, acted.content
        if category == "EL":
            authority = client(stub_iam, 3001, ("leave_cell.tasks.act", "leave_cell.tasks.view"))
            assert any(row["request_id"] == request_id for row in authority.get("/api/v1/leave/inbox/").json())
            approved = authority.post(
                f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
            )
            assert approved.status_code == 200, approved.content
            account = LeaveYearAccount.objects.get(employee_id="1001", leave_type="EL", year=2026)
            assert account.available_balance == 29

    # A replacement nominee must follow the same next-stage routing.
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001", "eligible_substitute_ids": ["4001", "4002"]}
    )
    LeaveEmployeeProfile.objects.update_or_create(employee_id="4002", defaults={})
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    created = applicant.post("/api/v1/leave/requests/", {
        "leave_type": "CL", "start_date": "2026-11-04", "end_date": "2026-11-04",
        "reason": "replacement routing", "substitute_id": "4001",
    }, format="json")
    assert created.status_code == 201, created.content
    request_id = created.json()["id"]
    first = client(stub_iam, 4001, ("leave_cell.tasks.act",))
    assert first.post(f"/api/v1/leave/requests/{request_id}/act/", {"action": "decline"}, format="json").status_code == 200
    applicant = client(stub_iam, 1001, ("leave_cell.requests.create", "leave_cell.tasks.act"))
    assert applicant.post(f"/api/v1/leave/requests/{request_id}/act/", {
        "action": "replace_substitute", "substitute_id": "4002",
    }, format="json").status_code == 200
    replacement = client(stub_iam, 4002, ("leave_cell.tasks.act",))
    assert replacement.post(f"/api/v1/leave/requests/{request_id}/act/", {"action": "accept"}, format="json").status_code == 200
    unit = client(stub_iam, 2001, ("leave_cell.tasks.view",))
    assert any(row["request_id"] == request_id for row in unit.get("/api/v1/leave/inbox/").json())


def test_configured_boundary_triggers_calendar_account_close_and_fails_closed():
    from datetime import datetime
    from unittest.mock import patch

    from django.utils import timezone

    from modules.leave.tasks import process_year_end_boundary

    LeaveEmployeeProfile.objects.create(employee_id="march-boundary")
    policy, _ = LeavePolicy.objects.get_or_create(key="current")
    policy.year_end_month = None
    policy.year_end_day = None
    policy.save()
    assert process_year_end_boundary("2027-03-31")["reason"] == "year-end boundary is not configured"
    policy.year_end_month, policy.year_end_day = 3, 31
    policy.save()
    assert process_year_end_boundary("2027-03-30")["year"] == 2025
    assert process_year_end_boundary("2027-03-31")["year"] == 2026
    assert LeaveYearAccount.objects.filter(employee_id="march-boundary", year=2027).exists()

    policy.year_end_month, policy.year_end_day = 4, 1
    policy.save()
    # 2028-03-31 20:00 UTC is already April 1 in the configured local zone.
    with timezone.override("Asia/Kolkata"), patch(
        "django.utils.timezone.now",
        return_value=datetime(2028, 3, 31, 20, 0, tzinfo=UTC),
    ):
        assert process_year_end_boundary()["year"] == 2027


def test_sla_threshold_processing_escalates_once_and_only_open_tasks():
    req = LeaveRequest.objects.create(
        employee_id="1001", leave_type="CL", start_date="2026-11-02", end_date="2026-11-02"
    )
    task = LeaveTask.objects.create(request=req, actor_id="2001", role="unit_head")
    LeaveTask.objects.filter(pk=task.pk).update(created_at=timezone.now() - timedelta(hours=9))
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001", defaults={"unit_head_id": "2001", "sanctioning_authority_id": "3001"}
    )
    LeaveSLAConfig.objects.create(
        role="unit_head",
        reminder_hours=2,
        escalation_hours=8,
        escalation_actor_id="3001",
        change_routing=True,
    )
    assert process_sla() == 1
    task.refresh_from_db()
    assert task.actor_id == "3001"
    assert LeaveSLAEvent.objects.filter(task=task, kind="escalation").count() == 1
    assert process_sla() == 0
    task.state = "completed"
    task.save()
    assert process_sla() == 0
