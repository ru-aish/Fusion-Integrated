from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from fusion_auth.permissions import HasModuleGrant, HasPermission

from ..models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeaveLedgerEntry,
    LeaveOfflineRecord,
    LeavePolicy,
    LeaveRequest,
    LeaveSLAConfig,
    LeaveTask,
    LeaveYearAccount,
    LeaveYearRun,
)
from ..serializers import (
    LeaveAccountSerializer,
    LeaveActionSerializer,
    LeaveAdjustmentResultSerializer,
    LeaveBalanceSerializer,
    LeaveCalendarDaySerializer,
    LeaveEmployeeProfileSerializer,
    LeaveExportSerializer,
    LeaveInboxItemSerializer,
    LeaveIssuanceResultSerializer,
    LeaveOfflineResultSerializer,
    LeaveOfflineRowSerializer,
    LeaveOfflineSyncSerializer,
    LeavePolicySerializer,
    LeaveRequestSerializer,
    LeaveResumeSerializer,
    LeaveSLAConfigSerializer,
    LeaveSLAProcessSerializer,
    LeaveTransitionSerializer,
    LeaveYearAdjustmentSerializer,
    LeaveYearCommandSerializer,
    LeaveYearEndListSerializer,
    LeaveYearRunSerializer,
)
from ..services import (
    act_on_request,
    create_offline_record,
    issue_entitlements,
    process_sla,
    run_year_end,
    submit_cancellation,
    submit_extension,
    submit_resumption,
)


class LeaveBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LeaveBalanceSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        HasPermission("leave_cell.balances.view"),
    ]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeaveBalance.objects.none()
        return LeaveBalance.objects.filter(employee_id=str(self.request.principal.user_id))


class LeaveAccountViewSet(viewsets.ViewSet):
    serializer_class = LeaveAccountSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        HasPermission("leave_cell.balances.view"),
    ]

    def list(self, request):
        rows = LeaveYearAccount.objects.filter(employee_id=str(request.principal.user_id)).order_by(
            "year", "leave_type"
        )
        result = []
        for row in rows:
            transactions = list(
                LeaveLedgerEntry.objects.filter(
                    employee_id=row.employee_id, leave_type=row.leave_type, year=row.year
                )
                .order_by("created_at")
                .values("amount", "kind", "reference", "actor_id", "created_at")
            )
            events = LeaveLedgerEntry.objects.filter(
                employee_id=row.employee_id,
                leave_type=row.leave_type,
                year=row.year,
                created_at__gte=row.created_at,
                kind__in={"credit", "debit", "adjustment", "lapse"},
            )
            ledger_net = sum((Decimal(str(event.amount)) for event in events), Decimal("0"))
            result.append(
                {
                    "employee_id": row.employee_id,
                    "leave_type": row.leave_type,
                    "year": row.year,
                    "opening_balance": row.opening_balance,
                    "available_balance": row.available_balance,
                    "source": row.source,
                    "ledger_balance": row.opening_balance + ledger_net,
                    "reconciled": row.opening_balance + ledger_net == row.available_balance,
                    "transactions": transactions,
                }
            )
        return Response(result)


class LeaveRequestReadPermission(permissions.BasePermission):
    """Owners and assigned officials can read their own respective scopes."""

    def has_permission(self, request, view):
        principal = getattr(request, "principal", None)
        return bool(
            principal
            and (
                principal.has_permission("leave_cell.requests.view")
                or principal.has_permission("leave_cell.tasks.view")
            )
        )


class LeaveRequestViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveRequestSerializer
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [permissions.IsAuthenticated, HasModuleGrant("leave_cell")]

    def get_permissions(self):
        if self.action == "act":
            submitted_action = (
                self.request.data.get("action") if self.request.method == "POST" else ""
            )
            permission = (
                "leave_cell.requests.create"
                if submitted_action in {"withdraw", "replace_substitute"}
                else "leave_cell.tasks.act"
            )
        else:
            if self.request.method == "POST":
                permission = "leave_cell.requests.create"
            elif self.request.query_params.get("scope") == "assigned":
                permission = "leave_cell.tasks.view"
            elif self.action in {"history", "export"} and self.request.method == "GET":
                permission = None
            else:
                permission = "leave_cell.requests.view"
        result = [
            permissions.IsAuthenticated(),
            HasModuleGrant("leave_cell")(),
        ]
        if permission:
            result.append(HasPermission(permission)())
        else:
            result.append(LeaveRequestReadPermission())
        return result

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeaveRequest.objects.none()
        qs = LeaveRequest.objects.all()
        if (
            self.action in {"act", "history", "export"}
            or self.request.query_params.get("scope") == "assigned"
        ):
            ids = LeaveTask.objects.filter(
                actor_id=str(self.request.principal.user_id)
            ).values_list("request_id", flat=True)
            if (
                self.action in {"history", "export"}
                or self.request.query_params.get("scope") == "assigned"
            ):
                return qs.filter(employee_id=str(self.request.principal.user_id)) | qs.filter(
                    pk__in=ids
                )
        return qs.filter(employee_id=str(self.request.principal.user_id))

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"], url_path="act")
    @extend_schema(request=LeaveActionSerializer, responses=LeaveRequestSerializer)
    def act(self, request, pk=None):
        obj = act_on_request(
            pk,
            request.principal.user_id,
            request.data.get("action", ""),
            request.data.get("note", ""),
            str(request.data.get("substitute_id", "")),
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["get"], url_path="history")
    @extend_schema(responses=LeaveTransitionSerializer(many=True))
    def history(self, request, pk=None):
        obj = self.get_object()
        substitute_view = LeaveTask.objects.filter(
            request=obj, actor_id=str(request.principal.user_id), role="substitute"
        ).exists()
        rows = obj.history.order_by("created_at").values(
            "actor_id", "action", "from_state", "to_state", "note", "created_at"
        )
        events = list(rows)
        if substitute_view:
            for event in events:
                event.pop("note", None)
        return Response(events)

    @action(detail=True, methods=["get"], url_path="export")
    @extend_schema(responses=LeaveExportSerializer)
    def export(self, request, pk=None):
        obj = self.get_object()
        substitute_view = LeaveTask.objects.filter(
            request=obj, actor_id=str(request.principal.user_id), role="substitute"
        ).exists()
        history = list(
            obj.history.order_by("created_at").values(
                "actor_id", "action", "from_state", "to_state", "note", "created_at"
            )
        )
        if substitute_view:
            for event in history:
                event.pop("note", None)
        exported = {
            "id": obj.id,
            "employee_id": obj.employee_id,
            "leave_type": obj.leave_type,
            "start_date": obj.start_date,
            "end_date": obj.end_date,
            "status": obj.status,
            "workflow_state": obj.workflow_state,
            "decision_history": history,
        }
        if not substitute_view:
            exported["reason"] = obj.reason
        return Response(exported)

    @action(detail=True, methods=["post"], url_path="cancel")
    @extend_schema(request=None, responses=LeaveRequestSerializer)
    def cancel(self, request, pk=None):
        obj = submit_cancellation(pk, request.principal.user_id, str(request.principal.user_id))
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="extend")
    @extend_schema(request=LeaveRequestSerializer, responses=LeaveRequestSerializer)
    def extend(self, request, pk=None):
        serializer = LeaveRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        obj = submit_extension(
            pk, request.principal.user_id, str(request.principal.user_id), serializer.validated_data
        )
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="resume")
    @extend_schema(request=LeaveResumeSerializer, responses=LeaveRequestSerializer)
    def resume(self, request, pk=None):
        try:
            actual_date = date.fromisoformat(request.data.get("actual_return_date", ""))
        except (TypeError, ValueError):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"actual_return_date": "Provide a valid ISO date."}) from None
        obj = submit_resumption(
            pk, request.principal.user_id, str(request.principal.user_id), actual_date
        )
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)


class LeaveInboxViewSet(viewsets.ViewSet):
    serializer_class = LeaveInboxItemSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        HasPermission("leave_cell.tasks.view"),
    ]

    def list(self, request):
        tasks = LeaveTask.objects.filter(actor_id=str(request.principal.user_id), state="open")
        return Response(
            [
                {
                    "task_id": t.id,
                    "request_id": t.request_id,
                    "role": t.role,
                    "workflow_state": t.request.workflow_state,
                    "leave_type": t.request.leave_type,
                    "start_date": t.request.start_date,
                    "end_date": t.request.end_date,
                }
                for t in tasks.select_related("request")
            ]
        )


class LeaveConfigurationPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        p = getattr(request, "principal", None)
        return bool(p and p.has_permission("leave_cell.configuration.manage"))


class LeaveOfflinePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        p = getattr(request, "principal", None)
        return bool(p and p.has_permission("leave_cell.offline.sync"))


class LeaveAccountsPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        p = getattr(request, "principal", None)
        return bool(p and p.has_permission("leave_cell.accounts.manage"))


class LeaveSLAPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        p = getattr(request, "principal", None)
        return bool(p and p.has_permission("leave_cell.sla.manage"))


class LeaveProfileViewSet(viewsets.ModelViewSet):
    queryset = LeaveEmployeeProfile.objects.all()
    serializer_class = LeaveEmployeeProfileSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveConfigurationPermission,
    ]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj, _ = LeaveEmployeeProfile.objects.update_or_create(
            employee_id=serializer.validated_data["employee_id"],
            defaults={k: v for k, v in serializer.validated_data.items() if k != "employee_id"},
        )
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)


class LeaveCalendarViewSet(viewsets.ModelViewSet):
    queryset = LeaveCalendarDay.objects.all().order_by("date")
    serializer_class = LeaveCalendarDaySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveConfigurationPermission,
    ]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        if serializer.validated_data.get("published"):
            raise ValidationError("Publish calendar entries through the atomic publish action.")
        serializer.save()

    def perform_update(self, serializer):
        if serializer.instance.published:
            raise ValidationError("Revise a published calendar through the atomic publish action.")
        if serializer.validated_data.get("published"):
            raise ValidationError("Publish calendar entries through the atomic publish action.")
        serializer.save()

    @action(detail=False, methods=["post"], url_path="publish")
    def publish(self, request):
        rows = LeaveCalendarDaySerializer(data=request.data, many=True)
        rows.is_valid(raise_exception=True)
        data = rows.validated_data
        if not data:
            raise ValidationError("A published calendar must contain at least one date.")
        keys = [(row["date"], row["kind"]) for row in data]
        if len(keys) != len(set(keys)):
            raise ValidationError("A calendar cannot contain duplicate date/category entries.")
        stamp = timezone.now()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [4128442026])
            list(LeaveCalendarDay.objects.select_for_update().filter(published=True))
            LeaveCalendarDay.objects.update(published=False)
            for row in data:
                LeaveCalendarDay.objects.update_or_create(
                    date=row["date"],
                    kind=row["kind"],
                    defaults={"label": row["label"], "published": True, "published_at": stamp},
                )
        return Response(
            LeaveCalendarDaySerializer(
                LeaveCalendarDay.objects.filter(published=True).order_by("date"), many=True
            ).data
        )


class LeavePolicyViewSet(viewsets.ViewSet):
    serializer_class = LeavePolicySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveConfigurationPermission,
    ]

    def list(self, request):
        return Response(
            LeavePolicySerializer(LeavePolicy.objects.filter(key="current"), many=True).data
        )

    def create(self, request):
        obj, _ = LeavePolicy.objects.get_or_create(key="current")
        serializer = LeavePolicySerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class LeaveOfflineViewSet(viewsets.ViewSet):
    serializer_class = LeaveOfflineSyncSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveOfflinePermission,
    ]

    @extend_schema(request=LeaveOfflineSyncSerializer, responses=LeaveOfflineResultSerializer)
    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj, created = create_offline_record(serializer.validated_data, request.principal.user_id)
        return Response(
            {"request_id": obj.pk, "workflow_state": obj.workflow_state, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses=LeaveOfflineRowSerializer(many=True))
    def list(self, request):
        return Response(
            list(
                LeaveOfflineRecord.objects.order_by("-created_at").values(
                    "external_id",
                    "employee_id",
                    "leave_type",
                    "start_date",
                    "end_date",
                    "sanction_reference",
                    "authority_id",
                    "source_reason",
                    "created_at",
                )
            )
        )


class LeaveYearEndViewSet(viewsets.ViewSet):
    serializer_class = LeaveYearCommandSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveAccountsPermission,
    ]

    @extend_schema(responses=LeaveYearEndListSerializer)
    def list(self, request):
        return Response(
            {
                "runs": list(LeaveYearRun.objects.order_by("-year").values()),
                "accounts": list(
                    LeaveYearAccount.objects.values(
                        "employee_id",
                        "leave_type",
                        "year",
                        "opening_balance",
                        "available_balance",
                        "source",
                    )
                ),
            }
        )

    @extend_schema(request=LeaveYearCommandSerializer, responses=LeaveYearRunSerializer)
    def create(self, request):
        try:
            year = int(request.data["year"])
        except (KeyError, ValueError, TypeError):
            raise ValidationError({"year": "Provide a valid closing year."}) from None
        run = run_year_end(year, request.principal.user_id)
        return Response({"year": run.year, "exceptions": run.exceptions}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="issue")
    @extend_schema(request=LeaveYearCommandSerializer, responses=LeaveIssuanceResultSerializer)
    def issue(self, request):
        try:
            year = int(request.data["year"])
        except (KeyError, ValueError, TypeError):
            raise ValidationError({"year": "Provide a valid issue year."}) from None
        run = issue_entitlements(year, request.principal.user_id)
        return Response({"year": run.year, "issued": True})

    @action(detail=False, methods=["post"], url_path="accounts/adjust")
    @extend_schema(request=LeaveYearAdjustmentSerializer, responses=LeaveAdjustmentResultSerializer)
    def adjust(self, request):
        serializer = LeaveYearAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        amount = d["amount"]
        year = d["year"]
        if amount == 0:
            raise ValidationError({"amount": "Adjustment cannot be zero."})
        with transaction.atomic():
            if (
                not LeaveEmployeeProfile.objects.select_for_update()
                .filter(employee_id=d["employee_id"])
                .exists()
            ):
                raise ValidationError(
                    {"employee_id": "No authoritative HR profile exists for this employee."}
                )
            if LeaveYearRun.objects.filter(year=year, exceptions=[]).exists():
                raise ValidationError(
                    {"year": "Closed calendar years require a separately audited reconciliation."}
                )
            acc = (
                LeaveYearAccount.objects.select_for_update()
                .filter(employee_id=d["employee_id"], leave_type=d["leave_type"], year=year)
                .first()
            )
            opening_credit = acc is None
            if not acc:
                if amount < 0:
                    raise ValidationError({"amount": "An opening account credit must be positive."})
                acc = LeaveYearAccount.objects.create(
                    employee_id=d["employee_id"],
                    leave_type=d["leave_type"],
                    year=year,
                    opening_balance=0,
                    available_balance=0,
                    source="admin_opening_credit",
                )
            if acc.available_balance + amount < 0:
                raise ValidationError({"amount": "Adjustment would make balance negative."})
            acc.available_balance += amount
            acc.save(update_fields=["available_balance"])
            from ..models import LeaveLedgerEntry

            LeaveLedgerEntry.objects.create(
                employee_id=acc.employee_id,
                leave_type=acc.leave_type,
                amount=amount,
                year=year,
                kind="credit" if opening_credit else "adjustment",
                reference=d["reason"],
                actor_id=str(request.principal.user_id),
            )
        return Response(
            {
                "employee_id": acc.employee_id,
                "leave_type": acc.leave_type,
                "year": year,
                "available_balance": acc.available_balance,
            }
        )


class LeaveSLAViewSet(viewsets.ViewSet):
    serializer_class = LeaveSLAConfigSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveSLAPermission,
    ]

    def list(self, request):
        return Response(list(LeaveSLAConfig.objects.values()))

    def create(self, request):
        s = self.serializer_class(data=request.data)
        s.is_valid(raise_exception=True)
        obj, _ = LeaveSLAConfig.objects.update_or_create(
            role=s.validated_data["role"],
            defaults={k: v for k, v in s.validated_data.items() if k != "role"},
        )
        return Response(self.serializer_class(obj).data)

    @action(detail=False, methods=["post"], url_path="process")
    @extend_schema(request=None, responses=LeaveSLAProcessSerializer)
    def process(self, request):
        return Response({"processed": process_sla()})
