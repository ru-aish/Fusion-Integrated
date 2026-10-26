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
    from .models import LeaveYearRun

    closing_year = today.year - 1
    existing = LeaveYearRun.objects.filter(year=closing_year).first()
    if existing and not existing.exceptions:
        return {"processed": False, "reason": "calendar year already closed"}
    from .services import run_year_end

    run = run_year_end(closing_year, "system")
    return {"processed": True, "year": run.year, "exceptions": run.exceptions}
