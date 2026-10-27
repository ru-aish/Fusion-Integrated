from datetime import date

from modules.leave.models import LeaveType, leave_days


def test_continuous_categories_count_intervening_weekends():
    assert leave_days(LeaveType.EL, date(2026, 11, 6), date(2026, 11, 9)) == 4
    assert leave_days(LeaveType.COL, date(2026, 11, 6), date(2026, 11, 9)) == 4
    assert leave_days(LeaveType.VL, date(2026, 11, 6), date(2026, 11, 9)) == 4


def test_other_categories_do_not_count_weekends_as_continuous_leave():
    for category in (LeaveType.CL, LeaveType.SCL, LeaveType.RH):
        assert leave_days(category, date(2026, 11, 6), date(2026, 11, 9)) == 2


def test_half_day_is_half_a_leave_day():
    assert leave_days(LeaveType.CL, date(2026, 11, 2), date(2026, 11, 2), 'first') == 0.5
