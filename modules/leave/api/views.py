from datetime import date

from django.db import connection, transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from fusion_auth.permissions import HasModuleGrant, HasPermission

from ..models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeavePolicy,
    LeaveRequest,
    LeaveTask,
)
from ..serializers import (
    LeaveBalanceSerializer,
    LeaveCalendarDaySerializer,
    LeaveEmployeeProfileSerializer,
    LeaveInboxItemSerializer,
    LeavePolicySerializer,
    LeaveRequestSerializer,
)
from ..services import act_on_request, submit_cancellation, submit_extension, submit_resumption


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
            permission = (
                "leave_cell.requests.create"
                if self.request.method == "POST"
                else "leave_cell.requests.view"
            )
        return [
            permissions.IsAuthenticated(),
            HasModuleGrant("leave_cell")(),
            HasPermission(permission)(),
        ]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeaveRequest.objects.none()
        qs = LeaveRequest.objects.all()
        if self.action in {"act", "history"}:
            ids = LeaveTask.objects.filter(
                actor_id=str(self.request.principal.user_id), state="open"
            ).values_list("request_id", flat=True)
            return qs.filter(employee_id=str(self.request.principal.user_id)) | qs.filter(
                pk__in=ids
            )
        if self.request.query_params.get("scope") == "assigned":
            ids = LeaveTask.objects.filter(
                actor_id=str(self.request.principal.user_id), state="open"
            ).values_list("request_id", flat=True)
            return qs.filter(pk__in=ids)
        return qs.filter(employee_id=str(self.request.principal.user_id))

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"], url_path="act")
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
    def history(self, request, pk=None):
        obj = self.get_object()
        rows = obj.history.order_by("created_at").values(
            "actor_id", "action", "from_state", "to_state", "note", "created_at"
        )
        return Response(list(rows))

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        obj = submit_cancellation(pk, request.principal.user_id, str(request.principal.user_id))
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="extend")
    def extend(self, request, pk=None):
        serializer = LeaveRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        obj = submit_extension(
            pk, request.principal.user_id, str(request.principal.user_id), serializer.validated_data
        )
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="resume")
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


class LeaveProfileViewSet(viewsets.ModelViewSet):
    queryset = LeaveEmployeeProfile.objects.all()
    serializer_class = LeaveEmployeeProfileSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        HasModuleGrant("leave_cell"),
        LeaveConfigurationPermission,
    ]
    http_method_names = ["get", "post", "patch", "head", "options"]


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
        return Response(LeaveCalendarDaySerializer(
            LeaveCalendarDay.objects.filter(published=True).order_by("date"), many=True
        ).data)


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
