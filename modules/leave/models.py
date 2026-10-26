from datetime import timedelta

from django.db import models


class LeaveType(models.TextChoices):
    CL = 'CL', 'Casual Leave'
    RH = 'RH', 'Restricted Holiday'
    SCL = 'SCL', 'Special Casual Leave'
    EL = 'EL', 'Earned Leave'
    COL = 'COL', 'Compensatory Off'
    VL = 'VL', 'Vacation Leave'


def leave_days(leave_type, start_date, end_date, half_day='none'):
    if half_day != 'none':
        return 0.5
    if leave_type in {LeaveType.EL, LeaveType.COL, LeaveType.VL}:
        return (end_date - start_date).days + 1
    # CL, SCL and RH do not use continuous interval counting. Until the
    # authoritative holiday calendar is integrated, weekends are excluded.
    return sum(
        1 for offset in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=offset)).weekday() < 5
    )

class LeaveBalance(models.Model):
    employee_id = models.CharField(max_length=64)
    leave_type = models.CharField(max_length=4, choices=LeaveType.choices)
    balance = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee_id', 'leave_type')

    def __str__(self):
        return f'{self.employee_id}: {self.leave_type}'

class LeaveRequest(models.Model):
    class HalfDay(models.TextChoices):
        NONE = 'none', 'Full day(s)'
        FIRST = 'first', 'First half'
        SECOND = 'second', 'Second half'

    employee_id = models.CharField(max_length=64)
    leave_type = models.CharField(max_length=4, choices=LeaveType.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    half_day = models.CharField(max_length=8, choices=HalfDay.choices, default=HalfDay.NONE)
    station_leave = models.BooleanField(default=False)
    station_leave_details = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.employee_id}: {self.start_date} to {self.end_date}'

    def duration(self):
        return leave_days(self.leave_type, self.start_date, self.end_date, self.half_day)
