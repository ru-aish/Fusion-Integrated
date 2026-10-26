"""Regression coverage for employee-scoped request validation."""
import pytest
from rest_framework.test import APIClient

from conftest import make_session
from modules.leave.models import LeaveBalance, LeaveRequest

pytestmark = pytest.mark.django_db


def _client(stub_iam, *, permissions=("leave_cell.requests.create",), user_id=1001):
    stub_iam(make_session(
        user_id=user_id, kind="staff", roles=("employee",), active_role="employee",
        modules=("leave_cell",), permissions=permissions,
    ))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token test")
    return client


def _balance(user_id=1001, category="CL", amount="8.0"):
    return LeaveBalance.objects.create(employee_id=str(user_id), leave_type=category,
                                       balance=amount)


def _payload(**values):
    return {"leave_type": "CL", "start_date": "2026-11-02", "end_date": "2026-11-02",
            "reason": "personal", **values}


def test_client_cannot_choose_owner_or_initial_state(stub_iam):
    _balance()
    response = _client(stub_iam).post("/api/v1/leave/requests/",
        _payload(employee_id="2002", status="approved"), format="json")
    assert response.status_code == 201
    assert response.json()["employee_id"] == "1001"
    assert response.json()["status"] == "pending"


def test_opposite_cl_halves_can_share_a_date_but_duplicate_half_cannot(stub_iam):
    _balance()
    client = _client(stub_iam)
    assert client.post("/api/v1/leave/requests/", _payload(half_day="first"),
                       format="json").status_code == 201
    assert client.post("/api/v1/leave/requests/", _payload(half_day="second"),
                       format="json").status_code == 201
    duplicate = client.post("/api/v1/leave/requests/", _payload(half_day="first"),
                            format="json")
    assert duplicate.status_code == 400


def test_full_day_cl_overlaps_and_wrong_half_day_categories_fail(stub_iam):
    _balance()
    LeaveRequest.objects.create(employee_id="1001", leave_type="CL",
        start_date="2026-11-02", end_date="2026-11-02", half_day="first")
    client = _client(stub_iam)
    assert client.post("/api/v1/leave/requests/", _payload(), format="json").status_code == 400
    wrong_type = client.post("/api/v1/leave/requests/",
        _payload(leave_type="EL", half_day="second"), format="json")
    assert wrong_type.status_code == 400


def test_requests_cannot_exceed_available_balance(stub_iam):
    _balance(amount="1.0")
    client = _client(stub_iam)
    assert client.post("/api/v1/leave/requests/", _payload(), format="json").status_code == 201
    too_much = client.post("/api/v1/leave/requests/",
        _payload(start_date="2026-11-03", end_date="2026-11-04"), format="json")
    assert too_much.status_code == 400


def test_station_leave_requires_details_and_create_permission(stub_iam):
    _balance()
    client = _client(stub_iam)
    missing = client.post("/api/v1/leave/requests/", _payload(station_leave=True),
                          format="json")
    assert missing.status_code == 400
    denied = _client(stub_iam, permissions=()).post(
        "/api/v1/leave/requests/", _payload(), format="json")
    assert denied.status_code == 403
