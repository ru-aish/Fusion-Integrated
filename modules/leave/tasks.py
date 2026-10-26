from datetime import date

from celery import shared_task
from django.utils import timezone


@shared_task(name="leave.process_sla", acks_late=True, reject_on_worker_lost=True)
def process_leave_sla():
    from .services import process_sla

    return process_sla()


@shared_task(name="leave.process_year_end_boundary", acks_late=True, reject_on_worker_lost=True)
def process_year_end_boundary(today=None):
    today = today or timezone.localdate()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    from .models import LeavePolicy, LeaveYearRun

    policy = LeavePolicy.objects.filter(key="current").first()
    if not policy or not policy.year_end_month or not policy.year_end_day:
        return {"processed": False, "reason": "year-end boundary is not configured"}
    try:
        boundary = date(today.year, policy.year_end_month, policy.year_end_day)
    except (TypeError, ValueError):
        return {"processed": False, "reason": "configured year-end boundary is invalid"}
    # Account and entitlement years remain Jan-Dec. The configured date is
    # only the trigger: close the latest calendar year whose boundary passed.
    closing_year = today.year - 1 if today >= boundary else today.year - 2
    if closing_year < 2000:
        return {"processed": False, "reason": "no complete calendar year is eligible"}
    existing = LeaveYearRun.objects.filter(year=closing_year).first()
    if existing and not existing.exceptions:
        return {"processed": False, "reason": "calendar year already closed"}
    from .services import run_year_end

    run = run_year_end(closing_year, "system")
    return {"processed": True, "year": run.year, "exceptions": run.exceptions}
