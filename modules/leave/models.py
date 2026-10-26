from datetime import timedelta

from django.db import models


class LeaveType(models.TextChoices):
    CL = "CL", "Casual Leave"
    RH = "RH", "Restricted Holiday"
    SCL = "SCL", "Special Casual Leave"
    EL = "EL", "Earned Leave"
    COL = "COL", "Compensatory Off"
    VL = "VL", "Vacation Leave"


def leave_days(leave_type, start_date, end_date, half_day="none"):
    if half_day != "none":
        return 0.5
    if leave_type in {LeaveType.EL, LeaveType.COL, LeaveType.VL}:
        return (end_date - start_date).days + 1
    # CL, SCL and RH do not use continuous interval counting. Until the
    # authoritative holiday calendar is integrated, weekends are excluded.
    return sum(
        1
        for offset in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=offset)).weekday() < 5
    )


class LeaveBalance(models.Model):
    employee_id = models.CharField(max_length=64)
    leave_type = models.CharField(max_length=4, choices=LeaveType.choices)
    balance = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee_id", "leave_type")

    def __str__(self):
        return f"{self.employee_id}: {self.leave_type}"


class LeaveRequest(models.Model):
    class HalfDay(models.TextChoices):
        NONE = "none", "Full day(s)"
        FIRST = "first", "First half"
        SECOND = "second", "Second half"

    employee_id = models.CharField(max_length=64)
    leave_type = models.CharField(max_length=4, choices=LeaveType.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    half_day = models.CharField(max_length=8, choices=HalfDay.choices, default=HalfDay.NONE)
    station_leave = models.BooleanField(default=False)
    station_leave_details = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, default="pending")
    workflow_state = models.CharField(max_length=48, default="awaiting_unit_head")
    substitute_id = models.CharField(max_length=64, blank=True)
    substitute_replacement_used = models.BooleanField(default=False)
    request_kind = models.CharField(
        max_length=16,
        default="new",
        choices=[
            ("new", "New leave"),
            ("cancellation", "Cancellation"),
            ("extension", "Extension"),
            ("resumption", "Resumption"),
        ],
    )
    parent_request = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="followups"
    )
    actual_return_date = models.DateField(null=True, blank=True)
    medical_evidence_reference = models.CharField(max_length=255, blank=True)
    recommendation = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee_id}: {self.start_date} to {self.end_date}"

    def duration(self):
        return leave_days(self.leave_type, self.start_date, self.end_date, self.half_day)


class LeaveEmployeeProfile(models.Model):
    """Authoritative routing and eligibility facts supplied by HR/IAM."""

    employee_id = models.CharField(max_length=64, unique=True)
    unit_head_id = models.CharField(max_length=64, blank=True)
    sanctioning_authority_id = models.CharField(max_length=64, blank=True)
    establishment_id = models.CharField(max_length=64, blank=True)
    establishment_required = models.BooleanField(default=False)
    is_director = models.BooleanField(default=False)
    is_faculty = models.BooleanField(default=False)
    substitute_required = models.BooleanField(default=False)
    eligible_substitute_ids = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.employee_id


class LeavePolicy(models.Model):
    """Single current policy row populated from the institution's approved rules."""

    key = models.CharField(max_length=24, unique=True, default="current")
    establishment_step = models.BooleanField(default=False)
    cl_annual = models.DecimalField(max_digits=5, decimal_places=1, default=8)
    rh_annual = models.DecimalField(max_digits=5, decimal_places=1, default=2)
    scl_annual = models.DecimalField(max_digits=5, decimal_places=1, default=15)
    el_annual = models.DecimalField(max_digits=5, decimal_places=1, default=30)
    vl_annual = models.DecimalField(max_digits=5, decimal_places=1, default=60)
    col_annual = models.DecimalField(max_digits=5, decimal_places=1, default=20)
    col_medical_evidence_required = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class LeaveCalendarDay(models.Model):
    """Published authoritative calendar entries; replacement is explicit."""

    date = models.DateField()
    kind = models.CharField(
        max_length=12,
        choices=[
            ("holiday", "Holiday"),
            ("rh", "Restricted Holiday"),
            ("vacation", "Academic vacation"),
        ],
    )
    label = models.CharField(max_length=160)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["date", "kind"], name="leave_calendar_date_kind_uniq")
        ]

    def __str__(self):
        return f"{self.date}: {self.kind}"


class LeaveTask(models.Model):
    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="tasks")
    actor_id = models.CharField(max_length=64)
    role = models.CharField(max_length=24)
    state = models.CharField(max_length=16, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.role} task for leave {self.request_id} ({self.state})"


class LeaveTransition(models.Model):
    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="history")
    actor_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    from_state = models.CharField(max_length=48)
    to_state = models.CharField(max_length=48)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.request_id}: {self.from_state} → {self.to_state}"


class LeaveLedgerEntry(models.Model):
    employee_id = models.CharField(max_length=64)
    leave_type = models.CharField(max_length=4, choices=LeaveType.choices)
    request = models.ForeignKey(LeaveRequest, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=6, decimal_places=1)
    kind = models.CharField(
        max_length=24,
        choices=[
            ("credit", "Credit"),
            ("reserve", "Reservation"),
            ("debit", "Debit"),
            ("release", "Release"),
            ("adjustment", "Adjustment"),
            ("lapse", "Year-end lapse"),
        ],
    )
    reference = models.CharField(max_length=100, blank=True)
    actor_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee_id}: {self.kind} {self.amount} {self.leave_type}"
