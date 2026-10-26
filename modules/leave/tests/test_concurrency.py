from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections
from rest_framework.exceptions import ValidationError

from modules.leave.models import LeaveBalance, LeaveEmployeeProfile, LeavePolicy
from modules.leave.services import submit_request

pytestmark = pytest.mark.django_db(transaction=True)


def test_overlapping_cross_category_submissions_serialize_on_employee_profile():
    LeavePolicy.objects.create(key="current")
    LeaveEmployeeProfile.objects.create(
        employee_id="5001", unit_head_id="7001", sanctioning_authority_id="7002"
    )
    LeaveBalance.objects.create(employee_id="5001", leave_type="CL", balance="8")
    LeaveBalance.objects.create(employee_id="5001", leave_type="EL", balance="30")
    gate = Barrier(2)

    def submit(category):
        close_old_connections()
        gate.wait(timeout=5)
        try:
            return submit_request(
                {
                    "leave_type": category,
                    "start_date": __import__("datetime").date(2026, 11, 2),
                    "end_date": __import__("datetime").date(2026, 11, 2),
                    "reason": "",
                    "half_day": "none",
                    "station_leave": False,
                    "station_leave_details": "",
                    "substitute_id": "",
                },
                "5001",
                "5001",
            )
        except ValidationError:
            return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ["CL", "EL"]))
    assert sum(value is not None for value in outcomes) == 1
