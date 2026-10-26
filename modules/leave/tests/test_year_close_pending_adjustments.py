"""Regression coverage for pending balance-changing workflows at annual close."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from rest_framework.exceptions import ValidationError

from modules.leave.models import (
    LeaveEmployeeProfile,
    LeaveLedgerEntry,
    LeavePolicy,
    LeaveRequest,
    LeaveTask,
    LeaveYearAccount,
    LeaveYearRun,
)
from modules.leave.services import (
    act_on_request,
    create_offline_record,
    run_year_end,
    submit_cancellation,
    submit_request,
    submit_resumption,
)

pytestmark = pytest.mark.django_db


def account(employee, category, year, opening, available):
    return LeaveYearAccount.objects.create(
        employee_id=employee,
        leave_type=category,
        year=year,
        opening_balance=opening,
        available_balance=available,
    )


def debit(employee, category, year, request, amount):
    LeaveLedgerEntry.objects.create(
        employee_id=employee,
        leave_type=category,
        year=year,
        request=request,
        amount=amount,
        kind="debit",
        reference="approved leave",
        actor_id="system",
    )


def test_pending_cancellation_is_resolved_before_cl_close_retry():
    emp = "qa-pending-cancel"
    LeaveEmployeeProfile.objects.create(employee_id=emp, unit_head_id="2001")
    old = account(emp, "CL", 2026, Decimal("8"), Decimal("6"))
    original = LeaveRequest.objects.create(
        employee_id=emp,
        leave_type="CL",
        start_date=date(2026, 12, 30),
        end_date=date(2026, 12, 31),
        workflow_state="approved",
        status="approved",
    )
    debit(emp, "CL", 2026, original, Decimal("-2"))
    cancellation = LeaveRequest.objects.create(
        employee_id=emp,
        leave_type="CL",
        start_date=original.start_date,
        end_date=original.end_date,
        request_kind="cancellation",
        parent_request=original,
        workflow_state="cancellation_unit_head",
    )
    LeaveTask.objects.create(request=cancellation, actor_id="2001", role="unit_head")

    closed = run_year_end(2026, "qa")
    assert closed.exceptions == [{"employee_id": emp, "leave_type": "CL", "reason": "pending requests remain at year end"}]
    act_on_request(cancellation.pk, 2001, "approve")
    retried = run_year_end(2026, "qa")
    old.refresh_from_db()
    next_cl = LeaveYearAccount.objects.get(employee_id=emp, leave_type="CL", year=2027)

    assert retried.exceptions == [], retried.exceptions
    assert old.available_balance == Decimal("0"), (
        "approved cancellation added credit to already-closed CL account: "
        f"2026={old.available_balance}; 2027={next_cl.available_balance}"
    )
    assert next_cl.available_balance == Decimal("8")


def test_pending_early_resumption_is_resolved_before_el_close_retry():
    emp = "qa-pending-resume"
    LeaveEmployeeProfile.objects.create(employee_id=emp, unit_head_id="2001")
    LeaveEmployeeProfile.objects.create(employee_id="qa-unaffected-retry", unit_head_id="2002")
    old = account(emp, "EL", 2026, Decimal("30"), Decimal("19"))
    account("qa-unaffected-retry", "EL", 2026, Decimal("30"), Decimal("5"))
    original = LeaveRequest.objects.create(
        employee_id=emp,
        leave_type="EL",
        start_date=date(2026, 10, 20),
        end_date=date(2026, 10, 30),
        workflow_state="approved",
        status="approved",
    )
    debit(emp, "EL", 2026, original, Decimal("-11"))
    resumption = LeaveRequest.objects.create(
        employee_id=emp,
        leave_type="EL",
        start_date=original.start_date,
        end_date=original.end_date,
        request_kind="resumption",
        parent_request=original,
        actual_return_date=date(2026, 10, 25),
        workflow_state="resumption_review_pending",
    )
    LeaveTask.objects.create(request=resumption, actor_id="3001", role="authority")
    LeaveEmployeeProfile.objects.filter(employee_id=emp).update(sanctioning_authority_id="3001")

    first = run_year_end(2026, "qa")
    assert first.exceptions == [{"employee_id": emp, "leave_type": "EL", "reason": "pending requests remain at year end"}]
    assert not LeaveYearAccount.objects.filter(
        employee_id="qa-unaffected-retry", leave_type="EL", year=2027
    ).exists()
    act_on_request(resumption.pk, 3001, "review_resumption")
    retried = run_year_end(2026, "qa")
    old.refresh_from_db()
    next_el = LeaveYearAccount.objects.get(employee_id=emp, leave_type="EL", year=2027)
    next_el.refresh_from_db()

    assert retried.exceptions == [], retried.exceptions
    assert old.available_balance == Decimal("0"), (
        "approved resumption adjustment is stranded in closed EL account: "
        f"2026={old.available_balance}; 2027={next_el.available_balance}"
    )
    assert next_el.available_balance == Decimal("55"), (
        "2027 EL should include 30 annual + 19 unused carry + 6 resumed leave days; "
        f"actual={next_el.available_balance}"
    )
    assert LeaveYearAccount.objects.get(
        employee_id="qa-unaffected-retry", leave_type="EL", year=2027
    ).available_balance == Decimal("35")


@pytest.mark.django_db(transaction=True)
def test_concurrent_close_replay_posts_once():
    from django.db import close_old_connections

    emp = "qa-concurrent-close"
    LeaveEmployeeProfile.objects.create(employee_id=emp)
    account(emp, "CL", 2026, Decimal("8"), Decimal("8"))
    gate = Barrier(2)

    def close():
        close_old_connections()
        gate.wait(timeout=5)
        result = run_year_end(2026, "qa-racer")
        close_old_connections()
        return result.year

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: close(), range(2))) == [2026, 2026]

    assert LeaveYearRun.objects.filter(year=2026).count() == 1
    assert LeaveLedgerEntry.objects.filter(
        employee_id=emp, leave_type="CL", year=2026, kind="lapse"
    ).count() == 1
    assert LeaveYearAccount.objects.get(
        employee_id=emp, leave_type="CL", year=2026
    ).available_balance == Decimal("0")
    assert LeaveYearAccount.objects.get(
        employee_id=emp, leave_type="CL", year=2027
    ).available_balance == Decimal("8")


def test_closed_calendar_year_rejects_new_and_followup_adjustments():
    emp = "qa-closed-year-adjustments"
    LeaveEmployeeProfile.objects.create(employee_id=emp, unit_head_id="2001", sanctioning_authority_id="3001")
    LeavePolicy.objects.get_or_create(key="current")
    account(emp, "CL", 2026, Decimal("8"), Decimal("8"))
    account(emp, "EL", 2026, Decimal("30"), Decimal("30"))
    run_year_end(2026, "qa")
    with pytest.raises(ValidationError, match="closed calendar year"):
        submit_request({"leave_type": "CL", "start_date": date(2026, 12, 1), "end_date": date(2026, 12, 1)}, emp, emp)
    with pytest.raises(ValidationError, match="closed calendar year"):
        create_offline_record({
            "external_id": "qa-closed-offline",
            "employee_id": emp,
            "leave_type": "CL",
            "start_date": "2026-12-01",
            "end_date": "2026-12-01",
            "reason": "closed year rejection",
            "sanction_reference": "QA-1",
            "authority_id": "2001",
            "source_reason": "sanction",
        }, "qa")
    approved_future = LeaveRequest.objects.create(
        employee_id=emp, leave_type="CL", start_date=date(2026, 12, 20),
        end_date=date(2026, 12, 20), workflow_state="approved", status="approved",
    )
    with pytest.raises(ValidationError, match="closed calendar year"):
        submit_cancellation(approved_future.pk, emp, emp)
    parent = LeaveRequest.objects.create(
        employee_id=emp, leave_type="EL", start_date=date(2026, 10, 1), end_date=date(2026, 10, 5),
        workflow_state="approved", status="approved",
    )
    with pytest.raises(ValidationError, match="closed calendar year"):
        submit_resumption(parent.pk, emp, emp, date(2026, 10, 3))


@pytest.mark.django_db(transaction=True)
def test_close_racing_cancellation_either_defers_or_rejects_without_losing_balance():
    from django.db import close_old_connections

    emp = "qa-close-cancel-race"
    LeaveEmployeeProfile.objects.create(employee_id=emp, unit_head_id="2001")
    old = account(emp, "CL", 2026, Decimal("8"), Decimal("8"))
    parent = LeaveRequest.objects.create(
        employee_id=emp, leave_type="CL", start_date=date(2026, 12, 20),
        end_date=date(2026, 12, 20), workflow_state="approved", status="approved",
    )
    gate = Barrier(2)

    def close():
        close_old_connections()
        gate.wait(timeout=5)
        result = run_year_end(2026, "qa-racer")
        close_old_connections()
        return result.exceptions

    def cancel():
        close_old_connections()
        gate.wait(timeout=5)
        try:
            submit_cancellation(parent.pk, emp, emp)
            result = "submitted"
        except ValidationError:
            result = "rejected"
        close_old_connections()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        close_result, cancel_result = list(pool.map(lambda fn: fn(), (close, cancel)))

    old.refresh_from_db()
    if cancel_result == "submitted":
        assert close_result == [{
            "employee_id": emp,
            "leave_type": "CL",
            "reason": "pending requests remain at year end",
        }]
        assert old.available_balance == Decimal("8")
    else:
        assert cancel_result == "rejected"
        assert close_result == []
        assert old.available_balance == Decimal("0")
        assert not LeaveRequest.objects.filter(
            employee_id=emp, request_kind="cancellation"
        ).exists()
