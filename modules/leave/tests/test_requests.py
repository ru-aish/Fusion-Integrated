"""Regression coverage for employee-scoped request validation."""

import pytest
from rest_framework.test import APIClient

from conftest import make_session
from modules.leave.models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeaveLedgerEntry,
    LeavePolicy,
    LeaveRequest,
    LeaveTask,
    LeaveTransition,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _authoritative_inputs():
    LeavePolicy.objects.get_or_create(key="current")
    LeaveEmployeeProfile.objects.update_or_create(
        employee_id="1001",
        defaults={
            "unit_head_id": "2001",
            "sanctioning_authority_id": "3001",
            "eligible_substitute_ids": ["4001"],
        },
    )


def _client(stub_iam, *, permissions=("leave_cell.requests.create",), user_id=1001):
    stub_iam(
        make_session(
            user_id=user_id,
            kind="staff",
            roles=("employee",),
            active_role="employee",
            modules=("leave_cell",),
            permissions=permissions,
        )
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token test")
    return client


def _balance(user_id=1001, category="CL", amount="8.0"):
    return LeaveBalance.objects.create(
        employee_id=str(user_id), leave_type=category, balance=amount
    )


def _payload(**values):
    return {
        "leave_type": "CL",
        "start_date": "2026-11-02",
        "end_date": "2026-11-02",
        "reason": "personal",
        **values,
    }


def test_client_cannot_choose_owner_or_initial_state(stub_iam):
    _balance()
    response = _client(stub_iam).post(
        "/api/v1/leave/requests/", _payload(employee_id="2002", status="approved"), format="json"
    )
    assert response.status_code == 201
    assert response.json()["employee_id"] == "1001"
    assert response.json()["status"] == "pending"


def test_opposite_cl_halves_can_share_a_date_but_duplicate_half_cannot(stub_iam):
    _balance()
    client = _client(stub_iam)
    assert (
        client.post(
            "/api/v1/leave/requests/", _payload(half_day="first"), format="json"
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/leave/requests/", _payload(half_day="second"), format="json"
        ).status_code
        == 201
    )
    duplicate = client.post("/api/v1/leave/requests/", _payload(half_day="first"), format="json")
    assert duplicate.status_code == 400


def test_full_day_cl_overlaps_and_wrong_half_day_categories_fail(stub_iam):
    _balance()
    LeaveRequest.objects.create(
        employee_id="1001",
        leave_type="CL",
        start_date="2026-11-02",
        end_date="2026-11-02",
        half_day="first",
    )
    client = _client(stub_iam)
    assert client.post("/api/v1/leave/requests/", _payload(), format="json").status_code == 400
    wrong_type = client.post(
        "/api/v1/leave/requests/", _payload(leave_type="EL", half_day="second"), format="json"
    )
    assert wrong_type.status_code == 400


def test_requests_cannot_exceed_available_balance(stub_iam):
    _balance(amount="1.0")
    client = _client(stub_iam)
    assert client.post("/api/v1/leave/requests/", _payload(), format="json").status_code == 201
    too_much = client.post(
        "/api/v1/leave/requests/",
        _payload(start_date="2026-11-03", end_date="2026-11-04"),
        format="json",
    )
    assert too_much.status_code == 400


def test_station_leave_requires_details_and_create_permission(stub_iam):
    _balance()
    client = _client(stub_iam)
    missing = client.post("/api/v1/leave/requests/", _payload(station_leave=True), format="json")
    assert missing.status_code == 400
    denied = _client(stub_iam, permissions=()).post(
        "/api/v1/leave/requests/", _payload(), format="json"
    )
    assert denied.status_code == 403


def test_assigned_unit_head_decides_cl_and_writes_history_and_ledger(stub_iam):
    _balance()
    applicant = _client(stub_iam)
    created = applicant.post("/api/v1/leave/requests/", _payload(), format="json")
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert created.json()["workflow_state"] == "awaiting_unit_head"
    assert LeaveTask.objects.filter(
        request_id=request_id, actor_id="2001", role="unit_head", state="open"
    ).exists()
    approver = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",))
    decision = approver.post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
    )
    assert decision.status_code == 200
    assert decision.json()["workflow_state"] == "approved"
    assert list(
        LeaveTransition.objects.filter(request_id=request_id).values_list("to_state", flat=True)
    ) == ["awaiting_unit_head", "approved"]
    assert list(
        LeaveLedgerEntry.objects.filter(request_id=request_id).values_list("kind", flat=True)
    ) == ["reserve", "release", "debit"]


def test_unassigned_actor_cannot_decide(stub_iam):
    _balance()
    created = _client(stub_iam).post("/api/v1/leave/requests/", _payload(), format="json")
    denied = _client(stub_iam, user_id=9999, permissions=("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{created.json()['id']}/act/", {"action": "approve"}, format="json"
    )
    assert denied.status_code == 403


def test_pending_withdrawal_closes_task_and_blocks_later_decision(stub_iam):
    _balance()
    created = _client(stub_iam).post('/api/v1/leave/requests/', _payload(), format='json')
    request_id = created.json()['id']
    withdrawn = _client(stub_iam).post(f'/api/v1/leave/requests/{request_id}/act/',
        {'action': 'withdraw'}, format='json')
    assert withdrawn.status_code == 200
    assert withdrawn.json()['workflow_state'] == 'withdrawn'
    assert not LeaveTask.objects.filter(request_id=request_id, state='open').exists()
    late = _client(stub_iam, user_id=2001,
        permissions=('leave_cell.tasks.act',)).post(
            f'/api/v1/leave/requests/{request_id}/act/',
            {'action': 'approve'}, format='json')
    assert late.status_code == 403


def test_substitute_decline_replacement_then_accept(stub_iam):
    _balance()
    request = _client(stub_iam).post(
        "/api/v1/leave/requests/", _payload(substitute_id="4001"), format="json"
    )
    assert request.status_code == 201
    request_id = request.json()["id"]
    substitute = _client(stub_iam, user_id=4001, permissions=("leave_cell.tasks.act",))
    assert (
        substitute.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "decline"}, format="json"
        ).status_code
        == 200
    )
    applicant = _client(stub_iam)
    replacement = applicant.post(
        f"/api/v1/leave/requests/{request_id}/act/",
        {"action": "replace_substitute", "substitute_id": "4002"},
        format="json",
    )
    # The authoritative eligible list deliberately excludes 4002.
    assert replacement.status_code == 400
    LeaveEmployeeProfile.objects.filter(employee_id="1001").update(
        eligible_substitute_ids=["4001", "4002"]
    )
    assert (
        applicant.post(
            f"/api/v1/leave/requests/{request_id}/act/",
            {"action": "replace_substitute", "substitute_id": "4002"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        _client(stub_iam, user_id=4002, permissions=("leave_cell.tasks.act",))
        .post(f"/api/v1/leave/requests/{request_id}/act/", {"action": "accept"}, format="json")
        .json()["workflow_state"]
        == "awaiting_unit_head"
    )


def test_substitute_recovery_allows_only_one_replacement(stub_iam):
    _balance()
    LeaveEmployeeProfile.objects.filter(employee_id="1001").update(
        eligible_substitute_ids=["4001", "4002"]
    )
    created = _client(stub_iam).post(
        "/api/v1/leave/requests/", _payload(substitute_id="4001"), format="json"
    )
    request_id = created.json()["id"]
    sub_one = _client(stub_iam, user_id=4001, permissions=("leave_cell.tasks.act",))
    assert sub_one.post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "decline"}, format="json"
    ).status_code == 200
    applicant = _client(stub_iam)
    assert applicant.post(
        f"/api/v1/leave/requests/{request_id}/act/",
        {"action": "replace_substitute", "substitute_id": "4002"}, format="json",
    ).status_code == 200
    sub_two = _client(stub_iam, user_id=4002, permissions=("leave_cell.tasks.act",))
    assert sub_two.post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "decline"}, format="json"
    ).status_code == 200
    applicant = _client(stub_iam)
    retry = applicant.post(
        f"/api/v1/leave/requests/{request_id}/act/",
        {"action": "replace_substitute", "substitute_id": "4001"}, format="json",
    )
    assert retry.status_code == 400


def _approved_cl(stub_iam):
    _balance()
    created = _client(stub_iam).post("/api/v1/leave/requests/", _payload(), format="json")
    request_id = created.json()["id"]
    response = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
    )
    assert response.status_code == 200
    return request_id


def test_prestart_cancellation_uses_separate_task_and_refunds_on_approval(stub_iam):
    original_id = _approved_cl(stub_iam)
    applicant = _client(stub_iam)
    response = applicant.post(f"/api/v1/leave/requests/{original_id}/cancel/", {}, format="json")
    assert response.status_code == 201
    cancellation_id = response.json()["id"]
    assert response.json()["request_kind"] == "cancellation"
    approved = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{cancellation_id}/act/", {"action": "approve"}, format="json"
    )
    assert approved.status_code == 200
    assert LeaveRequest.objects.get(pk=original_id).workflow_state == "cancelled"
    assert LeaveLedgerEntry.objects.filter(
        request_id=original_id, kind="adjustment", reference="approved cancellation"
    ).exists()


def test_rejected_cancellation_preserves_approved_original(stub_iam):
    original_id = _approved_cl(stub_iam)
    response = _client(stub_iam).post(
        f"/api/v1/leave/requests/{original_id}/cancel/", {}, format="json"
    )
    cancellation_id = response.json()["id"]
    rejected = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{cancellation_id}/act/", {"action": "reject"}, format="json"
    )
    assert rejected.status_code == 200
    assert LeaveRequest.objects.get(pk=original_id).workflow_state == "approved"


def test_cancellation_after_start_is_rejected(stub_iam):
    _balance()
    start_today = _payload(start_date="2026-10-26", end_date="2026-10-26")
    created = _client(stub_iam).post("/api/v1/leave/requests/", start_today, format="json")
    request_id = created.json()["id"]
    _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",)).post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
    )
    response = _client(stub_iam).post(
        f"/api/v1/leave/requests/{request_id}/cancel/", {}, format="json"
    )
    assert response.status_code == 400


def test_pending_cancellation_does_not_consume_a_second_balance_commitment(stub_iam):
    original_id = _approved_cl(stub_iam)
    applicant = _client(stub_iam)
    assert applicant.post(f"/api/v1/leave/requests/{original_id}/cancel/", {}, format="json").status_code == 201
    replacement = applicant.post(
        "/api/v1/leave/requests/",
        _payload(start_date="2026-11-03", end_date="2026-11-11"),
        format="json",
    )
    assert replacement.status_code == 201, replacement.data


def _approved_el(stub_iam, end_date):
    LeaveBalance.objects.create(employee_id="1001", leave_type="EL", balance="30")
    response = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "EL",
            "start_date": "2026-10-20",
            "end_date": end_date,
            "reason": "official work",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    request_id = response.json()["id"]
    unit_head = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",))
    assert (
        unit_head.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "recommend"}, format="json"
        ).status_code
        == 200
    )
    authority = _client(stub_iam, user_id=3001, permissions=("leave_cell.tasks.act",))
    assert (
        authority.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
        ).status_code
        == 200
    )
    return request_id


def test_extension_posts_increment_and_updates_original_end(stub_iam):
    original_id = _approved_el(stub_iam, "2026-10-30")
    applicant = _client(stub_iam)
    extension = applicant.post(
        f"/api/v1/leave/requests/{original_id}/extend/",
        {
            "leave_type": "EL",
            "start_date": "2026-10-31",
            "end_date": "2026-11-01",
            "reason": "extension",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    assert extension.status_code == 201, extension.data
    ext_id = extension.json()["id"]
    assert extension.json()["request_kind"] == "extension"
    unit_head = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",))
    unit_head.post(f"/api/v1/leave/requests/{ext_id}/act/", {"action": "recommend"}, format="json")
    authority = _client(stub_iam, user_id=3001, permissions=("leave_cell.tasks.act",))
    assert (
        authority.post(
            f"/api/v1/leave/requests/{ext_id}/act/", {"action": "approve"}, format="json"
        ).status_code
        == 200
    )
    assert LeaveRequest.objects.get(pk=original_id).end_date.isoformat() == "2026-11-01"
    assert LeaveLedgerEntry.objects.filter(request_id=ext_id, kind="debit", amount="-2.0").exists()


def test_approved_extension_is_not_double_counted_after_parent_end_is_updated(stub_iam):
    original_id = _approved_el(stub_iam, "2026-10-30")
    extension = _client(stub_iam).post(
        f"/api/v1/leave/requests/{original_id}/extend/",
        {
            "leave_type": "EL",
            "start_date": "2026-10-31",
            "end_date": "2026-11-01",
            "reason": "extension",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    extension_id = extension.json()["id"]
    head = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",))
    head.post(f"/api/v1/leave/requests/{extension_id}/act/", {"action": "recommend"}, format="json")
    authority = _client(stub_iam, user_id=3001, permissions=("leave_cell.tasks.act",))
    assert authority.post(
        f"/api/v1/leave/requests/{extension_id}/act/", {"action": "approve"}, format="json"
    ).status_code == 200

    next_request = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "EL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-18",
            "reason": "planned leave",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    assert next_request.status_code == 201, next_request.data


@pytest.mark.parametrize(
    ("planned_end", "return_date", "expected_state", "synchronized_end"),
    [
        ("2026-10-30", "2026-10-25", "resumption_early_synchronized", "2026-10-24"),
        ("2026-10-26", "2026-10-26", "resumption_no_adjustment", "2026-10-26"),
        ("2026-10-24", "2026-10-26", "resumption_late_synchronized", "2026-10-25"),
    ],
)
def test_resumption_review_normal_early_and_late(
    stub_iam, planned_end, return_date, expected_state, synchronized_end
):
    original_id = _approved_el(stub_iam, planned_end)
    applicant = _client(stub_iam)
    submitted = applicant.post(
        f"/api/v1/leave/requests/{original_id}/resume/",
        {"actual_return_date": return_date},
        format="json",
    )
    assert submitted.status_code == 201, submitted.data
    review_id = submitted.json()["id"]
    authority = _client(stub_iam, user_id=3001, permissions=("leave_cell.tasks.act",))
    reviewed = authority.post(
        f"/api/v1/leave/requests/{review_id}/act/", {"action": "review_resumption"}, format="json"
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["workflow_state"] == expected_state
    assert LeaveRequest.objects.get(pk=original_id).end_date.isoformat() == synchronized_end


def test_rh_requires_an_effectively_published_holiday(stub_iam):
    _balance(category="RH", amount="2")
    client = _client(stub_iam)
    payload = _payload(leave_type="RH")
    assert client.post("/api/v1/leave/requests/", payload, format="json").status_code == 400
    LeaveCalendarDay.objects.create(
        date="2026-11-02", kind="rh", label="Published RH", published=True
    )
    assert client.post("/api/v1/leave/requests/", payload, format="json").status_code == 201


def test_zero_charge_weekend_request_is_rejected(stub_iam):
    _balance()
    response = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        _payload(start_date="2026-11-07", end_date="2026-11-08"),
        format="json",
    )
    assert response.status_code == 400
    assert "no chargeable leave days" in str(response.json())


def test_col_medical_evidence_is_enforced_only_when_configured(stub_iam):
    _balance(category="COL", amount="20")
    client = _client(stub_iam)
    payload = _payload(leave_type="COL")
    assert client.post("/api/v1/leave/requests/", payload, format="json").status_code == 201

    LeavePolicy.objects.filter(key="current").update(col_medical_evidence_required=True)
    next_payload = _payload(leave_type="COL", start_date="2026-11-03", end_date="2026-11-03")
    assert client.post("/api/v1/leave/requests/", next_payload, format="json").status_code == 400
    next_payload["medical_evidence_reference"] = "MED-REF-2026-11"
    response = client.post("/api/v1/leave/requests/", next_payload, format="json")
    assert response.status_code == 201
    assert response.json()["medical_evidence_reference"] == "MED-REF-2026-11"


def test_calendar_publish_replaces_effective_set_atomically(stub_iam):
    old = LeaveCalendarDay.objects.create(
        date="2026-11-02", kind="rh", label="Old calendar", published=True
    )
    admin = _client(stub_iam, permissions=("leave_cell.configuration.manage",))
    response = admin.post(
        "/api/v1/leave/calendar/publish/",
        [{"date": "2026-12-01", "kind": "rh", "label": "New calendar"}],
        format="json",
    )
    assert response.status_code == 200, response.data
    old.refresh_from_db()
    assert not old.published
    assert list(
        LeaveCalendarDay.objects.filter(published=True).values_list("label", flat=True)
    ) == ["New calendar"]
    failed = admin.post("/api/v1/leave/calendar/publish/", [], format="json")
    assert failed.status_code == 400
    assert LeaveCalendarDay.objects.filter(published=True, label="New calendar").exists()


def test_optional_establishment_routing_precedes_final_authority(stub_iam):
    _balance(category="EL", amount="30")
    LeaveEmployeeProfile.objects.filter(employee_id="1001").update(
        establishment_required=True, establishment_id="2500"
    )
    request = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "EL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "reason": "work",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    request_id = request.json()["id"]
    unit_head = _client(stub_iam, user_id=2001, permissions=("leave_cell.tasks.act",))
    routed = unit_head.post(
        f"/api/v1/leave/requests/{request_id}/act/", {"action": "recommend"}, format="json"
    )
    assert routed.json()["workflow_state"] == "awaiting_establishment"
    establishment = _client(stub_iam, user_id=2500, permissions=("leave_cell.tasks.act",))
    assert (
        establishment.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "route"}, format="json"
        ).json()["workflow_state"]
        == "awaiting_authority"
    )
    authority = _client(stub_iam, user_id=3001, permissions=("leave_cell.tasks.act",))
    assert (
        authority.post(
            f"/api/v1/leave/requests/{request_id}/act/", {"action": "approve"}, format="json"
        ).json()["workflow_state"]
        == "approved"
    )


def test_director_self_sanction_requires_director_assignment(stub_iam):
    _balance(category="EL", amount="30")
    LeaveEmployeeProfile.objects.filter(employee_id="1001").update(
        is_director=True, sanctioning_authority_id="1001"
    )
    response = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "EL",
            "start_date": "2026-11-02",
            "end_date": "2026-11-02",
            "reason": "director leave",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["workflow_state"] == "awaiting_director"
    denied_profile = LeaveEmployeeProfile.objects.get(employee_id="1001")
    denied_profile.sanctioning_authority_id = "3001"
    denied_profile.save()
    failed = _client(stub_iam).post(
        "/api/v1/leave/requests/",
        {
            "leave_type": "EL",
            "start_date": "2026-11-03",
            "end_date": "2026-11-03",
            "reason": "misrouted",
            "half_day": "none",
            "station_leave": False,
            "station_leave_details": "",
        },
        format="json",
    )
    assert failed.status_code == 400
