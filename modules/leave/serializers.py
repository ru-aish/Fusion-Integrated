from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers

from .models import LeaveBalance, LeaveCalendarDay, LeaveEmployeeProfile, LeavePolicy, LeaveRequest

ACTIVE_STATES = {
    "awaiting_substitute",
    "applicant_action_required",
    "awaiting_unit_head",
    "awaiting_establishment",
    "awaiting_authority",
    "awaiting_director",
    "cancellation_unit_head",
    "cancellation_establishment",
    "cancellation_authority",
    "approved",
}


class LeaveBalanceSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()

    class Meta:
        model = LeaveBalance
        fields = ["employee_id", "leave_type", "balance", "available_balance", "last_updated"]

    def get_available_balance(self, obj) -> Decimal:
        committed = sum(
            (
                Decimal(str(request.duration()))
                for request in LeaveRequest.objects.filter(
                    employee_id=obj.employee_id,
                    leave_type=obj.leave_type,
                ).filter(
                    Q(request_kind="new", workflow_state__in=ACTIVE_STATES)
                    | Q(request_kind="extension", workflow_state__in=ACTIVE_STATES - {"approved"})
                )
            ),
            Decimal("0"),
        )
        return max(Decimal("0"), obj.balance - committed)


class LeaveRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "employee_id",
            "leave_type",
            "start_date",
            "end_date",
            "reason",
            "half_day",
            "station_leave",
            "station_leave_details",
            "status",
            "workflow_state",
            "substitute_id",
            "substitute_replacement_used",
            "request_kind",
            "parent_request",
            "actual_return_date",
            "medical_evidence_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "employee_id",
            "status",
            "workflow_state",
            "request_kind",
            "parent_request",
            "actual_return_date",
            "substitute_replacement_used",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        leave_type = attrs.get("leave_type", getattr(self.instance, "leave_type", None))
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        half_day = attrs.get("half_day", getattr(self.instance, "half_day", "none"))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "End date must be on or after start date."}
            )
        if half_day != "none" and (leave_type != "CL" or start != end):
            raise serializers.ValidationError(
                {"half_day": "Half-day requests are supported only for one-day Casual Leave."}
            )
        if attrs.get("station_leave") and not attrs.get("station_leave_details", "").strip():
            raise serializers.ValidationError(
                {"station_leave_details": "Details are required when Station Leave applies."}
            )
        evidence = attrs.get("medical_evidence_reference", "").strip()
        if evidence and leave_type != "COL":
            raise serializers.ValidationError(
                {"medical_evidence_reference": "Medical evidence applies only to COL."}
            )
        if not start or not end or not leave_type:
            return attrs
        return attrs

    def create(self, validated_data):
        from .services import submit_request

        actor = self.context["request"].principal.user_id
        return submit_request(validated_data, str(actor), str(actor))


class LeaveEmployeeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveEmployeeProfile
        fields = "__all__"
        read_only_fields = ["updated_at"]


class LeaveCalendarDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveCalendarDay
        fields = "__all__"
        read_only_fields = ["published_at"]


class LeavePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicy
        fields = "__all__"
        read_only_fields = ["key", "updated_at"]


class LeaveInboxItemSerializer(serializers.Serializer):
    task_id = serializers.IntegerField()
    request_id = serializers.IntegerField()
    role = serializers.CharField()
    workflow_state = serializers.CharField()
    leave_type = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
