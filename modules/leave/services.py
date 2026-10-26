import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeaveIssuanceRun,
    LeaveLedgerEntry,
    LeaveOfflineRecord,
    LeavePolicy,
    LeaveRequest,
    LeaveSLAConfig,
    LeaveSLAEvent,
    LeaveTask,
    LeaveTransition,
    LeaveYearAccount,
    LeaveYearRun,
    leave_days,
)

PENDING_STATES = {
    "awaiting_substitute",
    "applicant_action_required",
    "awaiting_unit_head",
    "awaiting_establishment",
    "awaiting_authority",
    "awaiting_director",
    "cancellation_unit_head",
    "cancellation_establishment",
    "cancellation_authority",
}


@transaction.atomic
def issue_entitlements(year, actor_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [4128443000 + int(year)])
    existing = LeaveIssuanceRun.objects.filter(year=year).first()
    if existing:
        return existing
    policy = LeavePolicy.objects.filter(key="current").first()
    if not policy:
        raise ValidationError("Current leave policy is not configured.")
    amounts = {
        "CL": policy.cl_annual,
        "RH": policy.rh_annual,
        "SCL": policy.scl_annual,
        "EL": policy.el_annual,
        "VL": policy.vl_annual,
        "COL": policy.col_annual,
    }
    for profile in LeaveEmployeeProfile.objects.select_for_update().order_by("employee_id"):
        for category, amount in amounts.items():
            if (category == "EL" and profile.is_faculty) or (
                category == "VL" and not profile.is_faculty
            ):
                continue
            _, created = LeaveYearAccount.objects.get_or_create(
                employee_id=profile.employee_id,
                leave_type=category,
                year=year,
                defaults={
                    "opening_balance": 0,
                    "available_balance": amount,
                    "source": "annual",
                },
            )
            if created:
                LeaveLedgerEntry.objects.create(
                    employee_id=profile.employee_id,
                    leave_type=category,
                    amount=amount,
                    year=year,
                    kind="credit",
                    reference=f"annual entitlement {year}",
                    actor_id=str(actor_id),
                )
    return LeaveIssuanceRun.objects.create(year=year, actor_id=str(actor_id))


def _task(request, actor, role):
    if not actor:
        raise ValidationError("Required routing assignment is not configured.")
    task = LeaveTask.objects.create(request=request, actor_id=actor, role=role)
    try:
        from modules.placement.services.notifications import enqueue

        enqueue(
            topic="leave.task.assigned",
            dedupe_key=f"leave-task-assigned-{task.pk}",
            subject="Leave task assigned",
            body=f"Leave request {request.pk} is waiting for your review as {role}.",
            recipient_user_id=int(actor),
            payload={"request_id": request.pk, "task_id": task.pk, "role": role},
        )
    except (ValueError, TypeError):
        # Preserve auditable workflow assignment for non-IAM HR identifiers.
        pass
    return task


def _change_account(employee_id, leave_type, year, amount):
    account = (
        LeaveYearAccount.objects.select_for_update()
        .filter(employee_id=str(employee_id), leave_type=leave_type, year=year)
        .first()
    )
    if account:
        account.available_balance += Decimal(str(amount))
        account.save(update_fields=["available_balance"])


def _year_slices(category, start, end, half_day="none"):
    result = {}
    for year in range(start.year, end.year + 1):
        left = max(start, date(year, 1, 1))
        right = min(end, date(year, 12, 31))
        result[year] = Decimal(
            str(leave_days(category, left, right, half_day if left == right == start else "none"))
        )
    return result


@transaction.atomic
def submit_request(data, employee_id, actor_id):
    # Lock a shared employee row, so overlap checks serialize across categories.
    substitute = str(data.get("substitute_id") or "")
    # Lock applicant and nominee in a globally stable order to serialize mutual
    # nominations without creating a lock-order cycle.
    lock_ids = sorted({str(employee_id), substitute} - {""})
    locked = list(
        LeaveEmployeeProfile.objects.select_for_update()
        .filter(employee_id__in=lock_ids)
        .order_by("employee_id")
    )
    profile = next((p for p in locked if p.employee_id == str(employee_id)), None)
    if profile is None:
        raise ValidationError({"detail": "HR routing profile is not configured for this employee."})
    policy = LeavePolicy.objects.filter(key="current").first()
    if policy is None:
        raise ValidationError({"detail": "Current ELM policy is not configured."})
    category, start, end = data["leave_type"], data["start_date"], data["end_date"]
    evidence = str(data.get("medical_evidence_reference", "")).strip()
    if category == "COL" and policy.col_medical_evidence_required and not evidence:
        raise ValidationError(
            {"medical_evidence_reference": "Supporting medical evidence is required for COL."}
        )
    if category == "RH" and (
        start != end
        or not LeaveCalendarDay.objects.filter(date=start, kind="rh", published=True).exists()
    ):
        raise ValidationError(
            {"start_date": "RH must be a single date in the published RH calendar."}
        )
    if category == "VL":
        if not profile.is_faculty:
            raise ValidationError({"leave_type": "Vacation Leave is limited to faculty."})
        days = (end - start).days + 1
        if (
            LeaveCalendarDay.objects.filter(
                date__range=(start, end), kind="vacation", published=True
            ).count()
            != days
        ):
            raise ValidationError(
                {"start_date": "VL must fall within published academic vacation dates."}
            )
    if (
        category == "EL"
        and profile.is_faculty
        and not LeaveYearAccount.objects.filter(
            employee_id=employee_id,
            leave_type="EL",
            year=start.year,
            source__in={"carryforward", "annual"},
        ).exists()
    ):
        raise ValidationError(
            {
                "leave_type": (
                    "Faculty EL is available only from an authorized VL conversion "
                    "or EL carryforward account."
                )
            }
        )
    if profile.substitute_required and not data.get("substitute_id"):
        raise ValidationError(
            {"substitute_id": "An eligible substitute is required for this request."}
        )
    if not profile.is_director and profile.sanctioning_authority_id == employee_id:
        raise ValidationError(
            {"detail": "Employee cannot be assigned as their own sanctioning authority."}
        )
    if profile.is_director and profile.sanctioning_authority_id != employee_id:
        raise ValidationError(
            {"detail": "Director self-sanction task must be assigned to the Director."}
        )
    # Cross-category overlap validation, permitting only opposite CL halves.
    overlap = LeaveRequest.objects.filter(
        employee_id=employee_id,
        workflow_state__in=PENDING_STATES | {"approved"},
        start_date__lte=end,
        end_date__gte=start,
    )
    if data.get("half_day") in {"first", "second"}:
        opposite = "second" if data["half_day"] == "first" else "first"
        overlap = overlap.exclude(
            leave_type="CL", start_date=start, end_date=end, half_day=opposite
        )
    if overlap.exists():
        raise ValidationError({"start_date": "This request overlaps pending or approved leave."})
    balance = (
        LeaveBalance.objects.select_for_update()
        .filter(employee_id=employee_id, leave_type=category)
        .first()
    )
    slices = _year_slices(category, start, end, data.get("half_day", "none"))
    amount = sum(slices.values(), Decimal("0"))
    if amount <= 0:
        raise ValidationError(
            {"start_date": "The selected dates contain no chargeable leave days."}
        )
    current_limit = {
        "CL": policy.cl_annual,
        "RH": policy.rh_annual,
        "SCL": policy.scl_annual,
        "VL": policy.vl_annual,
    }.get(category)
    accounts = {
        a.year: a
        for a in LeaveYearAccount.objects.select_for_update()
        .filter(employee_id=employee_id, leave_type=category, year__in=slices.keys())
        .order_by("year")
    }
    if len(slices) > 1 and len(accounts) != len(slices):
        raise ValidationError(
            {
                "leave_type": (
                    "Cross-year requests require an authoritative account for every affected year."
                )
            }
        )
    if not accounts and balance is None:
        raise ValidationError(
            {"leave_type": "No authoritative account is provisioned for this category."}
        )
    legacy_committed = sum(
        (
            Decimal(str(r.duration()))
            for r in LeaveRequest.objects.filter(
                employee_id=employee_id,
                leave_type=category,
                request_kind__in={"new", "extension"},
                workflow_state__in=PENDING_STATES | {"approved"},
            ).exclude(request_kind="extension", workflow_state="approved")
        ),
        Decimal("0"),
    )
    for year, days in slices.items():
        account = accounts.get(year)
        if account:
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            pending = LeaveRequest.objects.filter(
                employee_id=employee_id,
                leave_type=category,
                start_date__lte=year_end,
                end_date__gte=year_start,
                request_kind__in={"new", "extension"},
                workflow_state__in=PENDING_STATES,
            ).exclude(request_kind="extension", workflow_state="approved")
            reserved = sum(
                (
                    _year_slices(category, r.start_date, r.end_date, r.half_day).get(
                        year, Decimal("0")
                    )
                    for r in pending
                ),
                Decimal("0"),
            )
            available = account.available_balance
            committed = reserved
        else:
            if balance is None:
                raise ValidationError(
                    {"leave_type": f"No authoritative account is provisioned for {year}."}
                )
            available = (
                min(balance.balance, current_limit)
                if current_limit is not None
                else balance.balance
            )
            committed = legacy_committed
        if committed + days > available:
            raise ValidationError(
                {"leave_type": f"Insufficient available {category} account balance for {year}."}
            )
    if substitute and substitute not in (profile.eligible_substitute_ids or []):
        raise ValidationError(
            {"substitute_id": "Substitute is not in the authoritative eligible list."}
        )
    if substitute:
        if not any(p.employee_id == substitute for p in locked):
            raise ValidationError({"substitute_id": "Substitute HR profile is not configured."})
        if substitute == str(employee_id):
            raise ValidationError({"substitute_id": "Applicant cannot be their own substitute."})
        unavailable = LeaveRequest.objects.filter(
            employee_id=substitute,
            workflow_state__in=PENDING_STATES | {"approved"},
            start_date__lte=end,
            end_date__gte=start,
        ).exists()
        if unavailable:
            raise ValidationError(
                {"substitute_id": "Substitute has conflicting pending or approved leave."}
            )
    if substitute:
        state = "awaiting_substitute"
    elif profile.is_director:
        state = "awaiting_director"
    else:
        state = "awaiting_unit_head"
    obj = LeaveRequest.objects.create(employee_id=employee_id, **data, workflow_state=state)
    for year, days in slices.items():
        LeaveLedgerEntry.objects.create(
            employee_id=employee_id,
            leave_type=category,
            request=obj,
            amount=-days,
            year=year,
            kind="reserve",
            actor_id=actor_id,
        )
    if substitute:
        _task(obj, substitute, "substitute")
    elif state == "awaiting_director":
        _task(obj, profile.sanctioning_authority_id, "authority")
    else:
        _task(obj, profile.unit_head_id, "unit_head")
    LeaveTransition.objects.create(
        request=obj, actor_id=actor_id, action="submit", from_state="draft", to_state=state
    )
    return obj


@transaction.atomic
def create_offline_record(data, actor_id):
    required = (
        "external_id",
        "employee_id",
        "leave_type",
        "start_date",
        "end_date",
        "reason",
        "sanction_reference",
        "authority_id",
        "source_reason",
    )
    if any(not data.get(k) for k in required):
        raise ValidationError({"detail": "All offline sanction provenance fields are required."})
    data = dict(data)
    try:
        data["start_date"] = date.fromisoformat(str(data["start_date"]))
        data["end_date"] = date.fromisoformat(str(data["end_date"]))
    except (TypeError, ValueError):
        raise ValidationError({"start_date": "Provide valid ISO dates."}) from None
    canonical = {k: str(data[k]) for k in required}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [data["external_id"]])
    old = LeaveOfflineRecord.objects.filter(external_id=data["external_id"]).first()
    if old:
        if old.payload_hash == digest:
            return old.request, False
        raise ValidationError({"external_id": "External ID already exists with different content."})
    employee = str(data["employee_id"])
    profile = LeaveEmployeeProfile.objects.select_for_update().filter(employee_id=employee).first()
    if not profile:
        raise ValidationError({"employee_id": "Employee has no authoritative HR profile."})
    if data["start_date"] > data["end_date"]:
        raise ValidationError({"start_date": "Offline leave dates must be ordered."})
    allowed_authorities = {
        profile.unit_head_id,
        profile.sanctioning_authority_id,
        profile.establishment_id,
    }
    if profile.is_director:
        allowed_authorities.add(employee)
    if str(data["authority_id"]) not in allowed_authorities - {""}:
        raise ValidationError(
            {
                "authority_id": (
                    "Sanctioning authority does not match the employee's configured hierarchy."
                )
            }
        )
    expected_authority = (
        profile.unit_head_id
        if data["leave_type"] in {"CL", "RH"}
        else profile.sanctioning_authority_id
    )
    if profile.is_director:
        expected_authority = employee
    if str(data["authority_id"]) != str(expected_authority):
        raise ValidationError(
            {
                "authority_id": (
                    "Offline sanctioning actor does not match the final authority "
                    "for this leave category."
                )
            }
        )
    if data["leave_type"] not in {"CL", "RH", "SCL", "EL", "COL", "VL"}:
        raise ValidationError({"leave_type": "Select a supported leave category."})
    if data["leave_type"] == "RH" and (
        data["start_date"] != data["end_date"]
        or not LeaveCalendarDay.objects.filter(
            date=data["start_date"], kind="rh", published=True
        ).exists()
    ):
        raise ValidationError(
            {"start_date": "Offline RH must match one published restricted holiday."}
        )
    if data["leave_type"] == "VL" and not profile.is_faculty:
        raise ValidationError({"leave_type": "Vacation Leave is limited to faculty."})
    if (
        data["leave_type"] == "EL"
        and profile.is_faculty
        and not LeaveYearAccount.objects.filter(
            employee_id=employee,
            leave_type="EL",
            year=data["start_date"].year,
            source__in={"carryforward", "annual"},
        ).exists()
    ):
        raise ValidationError(
            {"leave_type": "Faculty EL requires an authorized conversion account."}
        )
    if data["leave_type"] == "VL":
        days = (data["end_date"] - data["start_date"]).days + 1
        if (
            LeaveCalendarDay.objects.filter(
                date__range=(data["start_date"], data["end_date"]), kind="vacation", published=True
            ).count()
            != days
        ):
            raise ValidationError(
                {"start_date": "Offline VL must fall within published academic vacation dates."}
            )
    if LeaveRequest.objects.filter(
        employee_id=employee,
        workflow_state__in=PENDING_STATES | {"approved"},
        start_date__lte=data["end_date"],
        end_date__gte=data["start_date"],
    ).exists():
        raise ValidationError(
            {"start_date": "Offline record conflicts with existing pending or approved leave."}
        )
    slices = _year_slices(data["leave_type"], data["start_date"], data["end_date"])
    accounts = {
        a.year: a
        for a in LeaveYearAccount.objects.select_for_update()
        .filter(employee_id=employee, leave_type=data["leave_type"], year__in=slices.keys())
        .order_by("year")
    }
    if len(accounts) != len(slices):
        raise ValidationError(
            {
                "leave_type": (
                    "Offline records require an authoritative year account for every affected year."
                )
            }
        )
    for yr, days in slices.items():
        account = accounts[yr]
        available = account.available_balance
        pending = LeaveRequest.objects.filter(
            employee_id=employee,
            leave_type=data["leave_type"],
            start_date__lte=date(yr, 12, 31),
            end_date__gte=date(yr, 1, 1),
            workflow_state__in=PENDING_STATES,
        )
        reserved = sum(
            (
                _year_slices(data["leave_type"], r.start_date, r.end_date, r.half_day).get(
                    yr, Decimal("0")
                )
                for r in pending
            ),
            Decimal("0"),
        )
        if days + reserved > available:
            raise ValidationError(
                {"leave_type": f"Offline sanction exceeds available balance in {yr}."}
            )
    req = LeaveRequest.objects.create(
        employee_id=employee,
        leave_type=data["leave_type"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        reason=data["reason"],
        workflow_state="approved",
        status="approved",
    )
    for yr, days in slices.items():
        LeaveLedgerEntry.objects.create(
            employee_id=employee,
            leave_type=req.leave_type,
            request=req,
            amount=-days,
            year=yr,
            kind="debit",
            reference=f"offline:{data['external_id']}",
            actor_id=str(actor_id),
        )
        _change_account(employee, req.leave_type, yr, -days)
    LeaveOfflineRecord.objects.create(**canonical, payload_hash=digest, request=req)
    LeaveTransition.objects.create(
        request=req,
        actor_id=str(actor_id),
        action="offline_sync",
        from_state="sanctioned_offline",
        to_state="approved",
        note=f"{data['sanction_reference']} — {data['source_reason']}",
    )
    return req, True


@transaction.atomic
def run_year_end(year, actor_id="system"):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [4128442000 + int(year)])
    existing_run = LeaveYearRun.objects.filter(year=year).first()
    if existing_run and not existing_run.exceptions:
        return existing_run
    exceptions = []
    employee_ids = list(
        LeaveYearAccount.objects.filter(year=year)
        .order_by("employee_id")
        .values_list("employee_id", flat=True)
        .distinct()
    )
    list(
        LeaveEmployeeProfile.objects.select_for_update()
        .filter(employee_id__in=employee_ids)
        .order_by("employee_id")
    )
    accounts = list(
        LeaveYearAccount.objects.select_for_update()
        .filter(year=year)
        .order_by("employee_id", "leave_type")
    )
    for account in accounts:
        profile = LeaveEmployeeProfile.objects.filter(employee_id=account.employee_id).first()
        pending = LeaveRequest.objects.filter(
            employee_id=account.employee_id,
            leave_type=account.leave_type,
            start_date__lte=date(year, 12, 31),
            end_date__gte=date(year, 1, 1),
            request_kind__in={"new", "extension"},
            workflow_state__in=PENDING_STATES,
        )
        if pending.exists():
            exceptions.append(
                {
                    "employee_id": account.employee_id,
                    "leave_type": account.leave_type,
                    "reason": "pending requests remain at year end",
                }
            )
            continue
        unused = max(Decimal("0"), account.available_balance)
        if account.leave_type in {"CL", "RH", "SCL", "VL"}:
            if account.leave_type == "VL" and profile and profile.is_faculty:
                conversion = unused / Decimal("2")
                target, _ = LeaveYearAccount.objects.get_or_create(
                    employee_id=account.employee_id,
                    leave_type="EL",
                    year=year + 1,
                    defaults={
                        "opening_balance": 0,
                        "available_balance": 0,
                        "source": "carryforward",
                    },
                )
                target.available_balance += conversion
                target.save()
                LeaveLedgerEntry.objects.create(
                    employee_id=account.employee_id,
                    leave_type="EL",
                    amount=conversion,
                    year=year + 1,
                    kind="credit",
                    reference=f"VL conversion {year}:2:1",
                    actor_id=str(actor_id),
                )
            account.available_balance = 0
            if unused:
                LeaveLedgerEntry.objects.create(
                    employee_id=account.employee_id,
                    leave_type=account.leave_type,
                    amount=-unused,
                    year=year,
                    kind="lapse",
                    reference=f"{account.leave_type} year-end lapse {year}",
                    actor_id=str(actor_id),
                )
        elif account.leave_type in {"EL", "COL"}:
            nxt, _ = LeaveYearAccount.objects.get_or_create(
                employee_id=account.employee_id,
                leave_type=account.leave_type,
                year=year + 1,
                defaults={"opening_balance": 0, "available_balance": 0, "source": "carryforward"},
            )
            nxt.available_balance += unused
            nxt.save()
            if unused:
                LeaveLedgerEntry.objects.create(
                    employee_id=account.employee_id,
                    leave_type=account.leave_type,
                    amount=unused,
                    year=year + 1,
                    kind="credit",
                    reference=f"{account.leave_type} carryforward {year}",
                    actor_id=str(actor_id),
                )
            account.available_balance = 0
            if unused:
                LeaveLedgerEntry.objects.create(
                    employee_id=account.employee_id,
                    leave_type=account.leave_type,
                    amount=-unused,
                    year=year,
                    kind="debit",
                    reference=f"{account.leave_type} carryforward transfer {year}",
                    actor_id=str(actor_id),
                )
        elif unused:
            LeaveLedgerEntry.objects.create(
                employee_id=account.employee_id,
                leave_type=account.leave_type,
                amount=-unused,
                year=year,
                kind="lapse",
                reference=f"{account.leave_type} year-end lapse {year}",
                actor_id=str(actor_id),
            )
        account.save(update_fields=["available_balance"])
    # Issue next-year annual credits once per account; run uniqueness protects replay.
    policy = LeavePolicy.objects.filter(key="current").first()
    for profile in LeaveEmployeeProfile.objects.all():
        amounts = (
            ("CL", policy.cl_annual if policy else 8),
            ("RH", policy.rh_annual if policy else 2),
            ("SCL", policy.scl_annual if policy else 15),
            ("EL", 0 if profile.is_faculty else (policy.el_annual if policy else 30)),
            ("VL", (policy.vl_annual if policy else 60) if profile.is_faculty else 0),
            ("COL", policy.col_annual if policy else 20),
        )
        for category, amount in amounts:
            if not amount:
                continue
            acc, created = LeaveYearAccount.objects.get_or_create(
                employee_id=profile.employee_id,
                leave_type=category,
                year=year + 1,
                defaults={"opening_balance": 0, "available_balance": 0, "source": "annual"},
            )
            if created or acc.source == "carryforward":
                acc.available_balance += Decimal(amount)
                acc.source = "annual"
                acc.save()
                LeaveLedgerEntry.objects.create(
                    employee_id=profile.employee_id,
                    leave_type=category,
                    amount=Decimal(amount),
                    year=year + 1,
                    kind="credit",
                    reference=f"annual entitlement {year + 1}",
                    actor_id=str(actor_id),
                )
    if existing_run:
        existing_run.exceptions = exceptions
        existing_run.actor_id = str(actor_id)
        existing_run.save(update_fields=["exceptions", "actor_id"])
        return existing_run
    return LeaveYearRun.objects.create(year=year, actor_id=str(actor_id), exceptions=exceptions)


@transaction.atomic
def process_sla(now=None):
    now = now or timezone.now()
    processed = 0
    for task in (
        LeaveTask.objects.select_for_update()
        .filter(state="open")
        .select_related("request")
        .order_by("pk")
    ):
        config = LeaveSLAConfig.objects.filter(role=task.role).first()
        if not config:
            continue
        if LeaveSLAEvent.objects.filter(task=task, kind="escalation").exists():
            continue
        age = (now - task.created_at).total_seconds() / 3600
        kind = None
        recipient = task.actor_id
        if (
            age >= config.escalation_hours
            and not LeaveSLAEvent.objects.filter(task=task, kind="escalation").exists()
        ):
            kind = "escalation"
            recipient = config.escalation_actor_id or task.actor_id
            profile = LeaveEmployeeProfile.objects.filter(
                employee_id=task.request.employee_id
            ).first()
            allowed = set()
            if profile and task.role == "unit_head":
                allowed = {profile.establishment_id, profile.sanctioning_authority_id}
            elif profile and task.role == "establishment":
                allowed = {profile.sanctioning_authority_id}
            else:
                allowed = set()
            routing_valid = bool(recipient in allowed and recipient)
            if config.change_routing and not routing_valid:
                recipient = task.actor_id
        elif (
            age >= config.reminder_hours
            and not LeaveSLAEvent.objects.filter(task=task, kind="reminder").exists()
        ):
            kind = "reminder"
        if not kind or task.state != "open":
            continue
        if (
            kind == "escalation"
            and config.change_routing
            and config.escalation_actor_id
            and routing_valid
        ):
            task.actor_id = config.escalation_actor_id
            task.save(update_fields=["actor_id"])
        LeaveSLAEvent.objects.create(task=task, kind=kind, recipient_id=recipient)
        LeaveTransition.objects.create(
            request=task.request,
            actor_id="system",
            action=f"sla_{kind}",
            from_state=task.request.workflow_state,
            to_state=task.request.workflow_state,
            note=f"SLA {kind} delivered to {recipient}",
        )
        try:
            from modules.placement.services.notifications import enqueue

            enqueue(
                topic="leave.task.reminder" if kind == "reminder" else "leave.task.escalated",
                dedupe_key=f"leave-sla-{task.pk}-{kind}",
                subject=f"Leave task {kind}",
                body=(
                    f"Leave request {task.request_id} remains pending. "
                    "Please review your assigned task."
                ),
                recipient_user_id=int(recipient),
                payload={"request_id": task.request_id, "task_id": task.pk, "kind": kind},
            )
        except (ValueError, TypeError):
            # Non-IAM HR identifiers remain auditable but cannot be mailed until
            # the directory gives the configured actor a numeric IAM identity.
            pass
        processed += 1
    return processed


@transaction.atomic
def submit_cancellation(original_id, employee_id, actor_id):
    original = LeaveRequest.objects.select_for_update().get(
        pk=original_id, employee_id=str(employee_id), workflow_state="approved"
    )
    if original.start_date <= date.today():
        raise ValidationError(
            {"detail": "Approved leave can only be cancelled before its start date."}
        )
    if original.followups.filter(
        request_kind="cancellation", workflow_state__in=PENDING_STATES
    ).exists():
        raise ValidationError({"detail": "A cancellation request is already pending."})
    profile = (
        LeaveEmployeeProfile.objects.select_for_update()
        .filter(employee_id=original.employee_id)
        .first()
    )
    if profile is None:
        raise ValidationError("Employee routing profile is unavailable.")
    state = "cancellation_unit_head"
    obj = LeaveRequest.objects.create(
        employee_id=original.employee_id,
        leave_type=original.leave_type,
        start_date=original.start_date,
        end_date=original.end_date,
        reason="Cancellation request",
        request_kind="cancellation",
        parent_request=original,
        workflow_state=state,
    )
    _task(obj, profile.unit_head_id, "unit_head")
    LeaveTransition.objects.create(
        request=obj,
        actor_id=str(actor_id),
        action="request_cancellation",
        from_state="approved",
        to_state=state,
    )
    return obj


@transaction.atomic
def submit_extension(original_id, employee_id, actor_id, data):
    original = LeaveRequest.objects.select_for_update().get(
        pk=original_id, employee_id=str(employee_id), workflow_state="approved"
    )
    if original.leave_type not in {"EL", "COL", "VL"}:
        raise ValidationError({"detail": "Only EL, COL, or VL can be extended."})
    if not original.start_date <= date.today() <= original.end_date:
        raise ValidationError({"detail": "Extension is available only while the leave is ongoing."})
    if data["start_date"] != original.end_date + timedelta(days=1):
        raise ValidationError(
            {"start_date": "Extension must begin the day after the approved end date."}
        )
    if data["leave_type"] != original.leave_type:
        raise ValidationError({"leave_type": "Extension category must match the approved leave."})
    obj = submit_request(data, str(employee_id), str(actor_id))
    obj.request_kind = "extension"
    obj.parent_request = original
    obj.save(update_fields=["request_kind", "parent_request"])
    return obj


@transaction.atomic
def submit_resumption(original_id, employee_id, actor_id, actual_return_date):
    original = LeaveRequest.objects.select_for_update().get(
        pk=original_id, employee_id=str(employee_id), workflow_state="approved"
    )
    if original.leave_type not in {"EL", "COL", "VL"}:
        raise ValidationError(
            {"detail": "Formal resumption review applies only to EL, COL, or VL."}
        )
    if actual_return_date > date.today() or actual_return_date < original.start_date:
        raise ValidationError(
            {"actual_return_date": "Return date must be after leave start and no later than today."}
        )
    if original.followups.filter(request_kind="resumption").exists():
        raise ValidationError({"detail": "Resumption has already been submitted."})
    profile = (
        LeaveEmployeeProfile.objects.select_for_update()
        .filter(employee_id=original.employee_id)
        .first()
    )
    if profile is None:
        raise ValidationError("Employee routing profile is unavailable.")
    state = "resumption_review_pending"
    obj = LeaveRequest.objects.create(
        employee_id=original.employee_id,
        leave_type=original.leave_type,
        start_date=original.start_date,
        end_date=original.end_date,
        reason="Resumption review",
        request_kind="resumption",
        parent_request=original,
        actual_return_date=actual_return_date,
        workflow_state=state,
    )
    _task(obj, profile.sanctioning_authority_id, "authority")
    LeaveTransition.objects.create(
        request=obj,
        actor_id=str(actor_id),
        action="submit_resumption",
        from_state="returned_from_leave",
        to_state=state,
    )
    return obj


@transaction.atomic
def act_on_request(obj_id, actor_id, action, note="", substitute_id=""):
    obj = LeaveRequest.objects.select_for_update().get(pk=obj_id)
    extra_lock = (
        str(substitute_id)
        if action == "replace_substitute"
        else str(actor_id)
        if action in {"accept", "decline"}
        else str(obj.employee_id)
    )
    profile_ids = sorted({str(obj.employee_id), extra_lock})
    locked_profiles = list(
        LeaveEmployeeProfile.objects.select_for_update()
        .filter(employee_id__in=profile_ids)
        .order_by("employee_id")
    )
    profile = next((p for p in locked_profiles if p.employee_id == str(obj.employee_id)), None)
    if profile is None:
        raise ValidationError("Employee routing profile is unavailable.")
    task = None
    if action not in {"withdraw", "replace_substitute"}:
        task = (
            LeaveTask.objects.select_for_update()
            .filter(request=obj, actor_id=str(actor_id), state="open")
            .first()
        )
        if task is None:
            raise PermissionDenied("No actionable task is assigned to this principal.")
        if task.role == "substitute" and not any(
            p.employee_id == str(actor_id) for p in locked_profiles
        ):
            raise ValidationError("Substitute HR profile is not configured.")
    before = obj.workflow_state
    if action in {"accept", "decline"}:
        if task.role != "substitute" or before != "awaiting_substitute":
            raise ValidationError("This request is not awaiting substitute consent.")
        if action == "decline":
            after = "applicant_action_required"
        else:
            # Recheck at consent time as the nominee's availability may have changed.
            unavailable = (
                LeaveRequest.objects.filter(
                    employee_id=str(actor_id),
                    workflow_state__in=PENDING_STATES | {"approved"},
                    start_date__lte=obj.end_date,
                    end_date__gte=obj.start_date,
                )
                .exclude(pk=obj.pk)
                .exists()
            )
            if unavailable:
                raise ValidationError("Substitute now has conflicting pending or approved leave.")
            after = "awaiting_unit_head" if not profile.is_director else "awaiting_director"
    elif action == "replace_substitute":
        if actor_id != int(obj.employee_id) or before != "applicant_action_required":
            raise PermissionDenied("Only the applicant can nominate a replacement at this stage.")
        if obj.substitute_replacement_used:
            raise ValidationError("Only one substitute replacement is allowed per request.")
        if substitute_id not in (profile.eligible_substitute_ids or []) or substitute_id == str(
            actor_id
        ):
            raise ValidationError({"substitute_id": "Replacement is not eligible."})
        if not any(p.employee_id == str(substitute_id) for p in locked_profiles):
            raise ValidationError({"substitute_id": "Replacement HR profile is not configured."})
        if LeaveRequest.objects.filter(
            employee_id=substitute_id,
            workflow_state__in=PENDING_STATES | {"approved"},
            start_date__lte=obj.end_date,
            end_date__gte=obj.start_date,
        ).exists():
            raise ValidationError(
                {"substitute_id": "Replacement has conflicting pending or approved leave."}
            )
        obj.substitute_id = substitute_id
        obj.substitute_replacement_used = True
        after = "awaiting_substitute"
        _task(obj, substitute_id, "substitute")
    elif action in {
        "approve",
        "reject",
        "recommend",
        "not_recommend",
        "route",
        "review_resumption",
    }:
        if task.role == "unit_head" and before in {"awaiting_unit_head", "cancellation_unit_head"}:
            higher_category = (
                obj.parent_request.leave_type
                if obj.request_kind == "cancellation"
                else obj.leave_type
            )
            is_cancellation = obj.request_kind == "cancellation"
            if higher_category in {"CL", "RH"}:
                if action not in {"approve", "reject"}:
                    raise ValidationError("CL/RH require a final Unit Head decision.")
                after = (
                    ("cancellation_approved" if action == "approve" else "cancellation_rejected")
                    if is_cancellation
                    else ("approved" if action == "approve" else "rejected")
                )
            else:
                if action not in {"recommend", "not_recommend"}:
                    raise ValidationError("Higher sanction requires a recommendation.")
                obj.recommendation = "recommended" if action == "recommend" else "not_recommended"
                after = (
                    (
                        "cancellation_establishment"
                        if profile.establishment_required
                        else "cancellation_authority"
                    )
                    if is_cancellation
                    else (
                        "awaiting_establishment"
                        if profile.establishment_required
                        else "awaiting_authority"
                    )
                )
                if after in {"awaiting_establishment", "cancellation_establishment"}:
                    _task(obj, profile.establishment_id, "establishment")
                else:
                    _task(obj, profile.sanctioning_authority_id, "authority")
        elif (
            task.role == "establishment"
            and before in {"awaiting_establishment", "cancellation_establishment"}
            and action == "route"
        ):
            after = (
                "cancellation_authority"
                if obj.request_kind == "cancellation"
                else "awaiting_authority"
            )
            _task(obj, profile.sanctioning_authority_id, "authority")
        elif task.role == "authority" and before in {
            "awaiting_authority",
            "awaiting_director",
            "cancellation_authority",
        }:
            if obj.request_kind == "cancellation":
                after = (
                    "cancellation_approved"
                    if action == "approve"
                    else "cancellation_rejected"
                    if action == "reject"
                    else None
                )
            else:
                after = (
                    "approved"
                    if action == "approve"
                    else "rejected"
                    if action == "reject"
                    else None
                )
            if after is None:
                raise ValidationError("Authority must approve or reject.")
        elif (
            task.role == "authority"
            and before == "resumption_review_pending"
            and action == "review_resumption"
        ):
            if obj.actual_return_date == obj.parent_request.end_date:
                after = "resumption_no_adjustment"
            elif obj.actual_return_date < obj.parent_request.end_date:
                after = "resumption_early_synchronized"
            else:
                after = "resumption_late_synchronized"
        else:
            raise ValidationError("Action does not match this task and workflow state.")
    elif action == "withdraw":
        if actor_id != int(obj.employee_id) or before not in PENDING_STATES:
            raise PermissionDenied("Only the applicant can withdraw a pending request.")
        after = "withdrawn"
    else:
        raise ValidationError("Unsupported action.")
    if task is not None:
        task.state = "completed"
        task.completed_at = timezone.now()
        task.save()
    obj.workflow_state = after
    if after in {
        "approved",
        "rejected",
        "withdrawn",
        "cancellation_approved",
        "cancellation_rejected",
        "resumption_no_adjustment",
        "resumption_early_synchronized",
        "resumption_late_synchronized",
    }:
        LeaveTask.objects.filter(request=obj, state="open").update(
            state="cancelled", completed_at=timezone.now()
        )
        if obj.request_kind == "cancellation":
            obj.status = "approved" if after == "cancellation_approved" else "rejected"
            if after == "cancellation_approved":
                original = LeaveRequest.objects.select_for_update().get(pk=obj.parent_request_id)
                original.workflow_state = "cancelled"
                original.status = "cancelled"
                original.save(update_fields=["workflow_state", "status", "updated_at"])
                for yr, days in _year_slices(
                    original.leave_type, original.start_date, original.end_date, original.half_day
                ).items():
                    LeaveLedgerEntry.objects.create(
                        employee_id=original.employee_id,
                        leave_type=original.leave_type,
                        request=original,
                        amount=days,
                        year=yr,
                        kind="adjustment",
                        reference="approved cancellation",
                        actor_id=str(actor_id),
                    )
                    _change_account(original.employee_id, original.leave_type, yr, days)
        elif obj.request_kind == "resumption":
            obj.status = "reviewed"
            original = LeaveRequest.objects.select_for_update().get(pk=obj.parent_request_id)
            old_slices = _year_slices(
                original.leave_type, original.start_date, original.end_date, original.half_day
            )
            if after == "resumption_early_synchronized" or after == "resumption_late_synchronized":
                original.end_date = obj.actual_return_date - timedelta(days=1)
            if after != "resumption_no_adjustment":
                new_slices = _year_slices(
                    original.leave_type, original.start_date, original.end_date, original.half_day
                )
                for yr in set(old_slices) | set(new_slices):
                    delta = old_slices.get(yr, Decimal("0")) - new_slices.get(yr, Decimal("0"))
                    if delta:
                        LeaveLedgerEntry.objects.create(
                            employee_id=original.employee_id,
                            leave_type=original.leave_type,
                            request=original,
                            amount=delta,
                            year=yr,
                            kind="adjustment",
                            reference=after,
                            actor_id=str(actor_id),
                        )
                        _change_account(original.employee_id, original.leave_type, yr, delta)
                original.save(update_fields=["end_date", "updated_at"])
        else:
            obj.status = after
            for yr, days in _year_slices(
                obj.leave_type, obj.start_date, obj.end_date, obj.half_day
            ).items():
                LeaveLedgerEntry.objects.create(
                    employee_id=obj.employee_id,
                    leave_type=obj.leave_type,
                    request=obj,
                    amount=days,
                    year=yr,
                    kind="release",
                    actor_id=str(actor_id),
                )
        if after == "approved":
            if obj.request_kind == "extension":
                original = LeaveRequest.objects.select_for_update().get(pk=obj.parent_request_id)
                original.end_date = obj.end_date
                original.save(update_fields=["end_date", "updated_at"])
            for yr, days in _year_slices(
                obj.leave_type, obj.start_date, obj.end_date, obj.half_day
            ).items():
                LeaveLedgerEntry.objects.create(
                    employee_id=obj.employee_id,
                    leave_type=obj.leave_type,
                    request=obj,
                    amount=-days,
                    year=yr,
                    kind="debit",
                    actor_id=str(actor_id),
                )
                _change_account(obj.employee_id, obj.leave_type, yr, -days)
    obj.save(
        update_fields=[
            "workflow_state",
            "status",
            "recommendation",
            "substitute_id",
            "substitute_replacement_used",
            "updated_at",
        ]
    )
    LeaveTransition.objects.create(
        request=obj,
        actor_id=str(actor_id),
        action=action,
        from_state=before,
        to_state=after,
        note=note,
    )
    return obj
