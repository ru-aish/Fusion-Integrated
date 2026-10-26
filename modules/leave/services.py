from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeaveLedgerEntry,
    LeavePolicy,
    LeaveRequest,
    LeaveTask,
    LeaveTransition,
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


def _task(request, actor, role):
    if not actor:
        raise ValidationError("Required routing assignment is not configured.")
    return LeaveTask.objects.create(request=request, actor_id=actor, role=role)


@transaction.atomic
def submit_request(data, employee_id, actor_id):
    # Lock a shared employee row, so overlap checks serialize across categories.
    profile = (
        LeaveEmployeeProfile.objects.select_for_update().filter(employee_id=employee_id).first()
    )
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
    if category == "EL" and profile.is_faculty:
        raise ValidationError(
            {"leave_type": "Faculty are not eligible for non-faculty Earned Leave."}
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
    if balance is None:
        raise ValidationError({"leave_type": "No leave balance is provisioned for this category."})
    amount = Decimal(str(LeaveRequest(employee_id=employee_id, **data).duration()))
    if amount <= 0:
        raise ValidationError(
            {"start_date": "The selected dates contain no chargeable leave days."}
        )
    committed = sum(
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
    current_limit = {
        "CL": policy.cl_annual,
        "RH": policy.rh_annual,
        "SCL": policy.scl_annual,
        "VL": policy.vl_annual,
    }.get(category)
    available = (
        min(balance.balance, current_limit) if current_limit is not None else balance.balance
    )
    if committed + amount > available:
        raise ValidationError({"leave_type": "Insufficient available leave balance."})
    substitute = str(data.get("substitute_id") or "")
    if substitute and substitute not in (profile.eligible_substitute_ids or []):
        raise ValidationError(
            {"substitute_id": "Substitute is not in the authoritative eligible list."}
        )
    if substitute:
        state = "awaiting_substitute"
    elif profile.is_director:
        state = "awaiting_director"
    else:
        state = "awaiting_unit_head"
    obj = LeaveRequest.objects.create(employee_id=employee_id, **data, workflow_state=state)
    LeaveLedgerEntry.objects.create(
        employee_id=employee_id,
        leave_type=category,
        request=obj,
        amount=-amount,
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
    profile = (
        LeaveEmployeeProfile.objects.select_for_update().filter(employee_id=obj.employee_id).first()
    )
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
    before = obj.workflow_state
    if action in {"accept", "decline"}:
        if task.role != "substitute" or before != "awaiting_substitute":
            raise ValidationError("This request is not awaiting substitute consent.")
        if action == "decline":
            after = "applicant_action_required"
        else:
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
                LeaveLedgerEntry.objects.create(
                    employee_id=original.employee_id,
                    leave_type=original.leave_type,
                    request=original,
                    amount=Decimal(str(original.duration())),
                    kind="adjustment",
                    reference="approved cancellation",
                    actor_id=str(actor_id),
                )
        elif obj.request_kind == "resumption":
            obj.status = "reviewed"
            original = LeaveRequest.objects.select_for_update().get(pk=obj.parent_request_id)
            old_days = Decimal(str(original.duration()))
            if after == "resumption_early_synchronized" or after == "resumption_late_synchronized":
                original.end_date = obj.actual_return_date - timedelta(days=1)
            if after != "resumption_no_adjustment":
                new_days = Decimal(str(original.duration()))
                LeaveLedgerEntry.objects.create(
                    employee_id=original.employee_id,
                    leave_type=original.leave_type,
                    request=original,
                    amount=old_days - new_days,
                    kind="adjustment",
                    reference=after,
                    actor_id=str(actor_id),
                )
                original.save(update_fields=["end_date", "updated_at"])
        else:
            obj.status = after
            LeaveLedgerEntry.objects.create(
                employee_id=obj.employee_id,
                leave_type=obj.leave_type,
                request=obj,
                amount=Decimal(str(obj.duration())),
                kind="release",
                actor_id=str(actor_id),
            )
        if after == "approved":
            if obj.request_kind == "extension":
                original = LeaveRequest.objects.select_for_update().get(pk=obj.parent_request_id)
                original.end_date = obj.end_date
                original.save(update_fields=["end_date", "updated_at"])
            LeaveLedgerEntry.objects.create(
                employee_id=obj.employee_id,
                leave_type=obj.leave_type,
                request=obj,
                amount=-Decimal(str(obj.duration())),
                kind="debit",
                actor_id=str(actor_id),
            )
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
