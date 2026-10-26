from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers

from .models import (
    LeaveBalance,
    LeaveCalendarDay,
    LeaveEmployeeProfile,
    LeavePolicy,
    LeaveRequest,
    LeaveSLAConfig,
    LeaveType,
)

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
    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request and getattr(request, "principal", None):
            from .models import LeaveTask

            assigned_as_substitute = LeaveTask.objects.filter(
                request_id=getattr(self.instance, "pk", None),
                actor_id=str(request.principal.user_id),
                role="substitute",
            ).exists()
            if assigned_as_substitute:
                fields.pop("medical_evidence_reference", None)
                fields.pop("reason", None)
                fields.pop("station_leave_details", None)
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and getattr(request, "principal", None):
            from .models import LeaveTask

            assigned_as_substitute = LeaveTask.objects.filter(
                request=instance,
                actor_id=str(request.principal.user_id),
                role="substitute",
            ).exists()
            if assigned_as_substitute:
                for field in ("medical_evidence_reference", "reason", "station_leave_details"):
                    data.pop(field, None)
        return data

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

    def validate(self, attrs):
        month = attrs.get("year_end_month", getattr(self.instance, "year_end_month", None))
        day = attrs.get("year_end_day", getattr(self.instance, "year_end_day", None))
        if (month is None) != (day is None):
            raise serializers.ValidationError("Configure both year-end month and day together.")
        if month is not None:
            from datetime import date

            try:
                date(2001, month, day)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {
                        "year_end_day": (
                            "Provide a valid annual boundary date; February 29 is not supported."
                        )
                    }
                ) from None
        return attrs


class LeaveInboxItemSerializer(serializers.Serializer):
    task_id = serializers.IntegerField()
    request_id = serializers.IntegerField()
    role = serializers.CharField()
    workflow_state = serializers.CharField()
    leave_type = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class LeaveOfflineSyncSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=120)
    employee_id = serializers.CharField(max_length=64)
    leave_type = serializers.ChoiceField(choices=LeaveType.choices)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField()
    sanction_reference = serializers.CharField(max_length=255)
    authority_id = serializers.CharField(max_length=64)
    source_reason = serializers.CharField(max_length=255)


class LeaveYearCommandSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2200)


class LeaveYearAdjustmentSerializer(LeaveYearCommandSerializer):
    employee_id = serializers.CharField(max_length=64)
    leave_type = serializers.ChoiceField(choices=LeaveType.choices)
    amount = serializers.DecimalField(max_digits=7, decimal_places=2)
    reason = serializers.CharField(max_length=500)


class LeaveAccountTransactionSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=7, decimal_places=2)
    kind = serializers.CharField()
    reference = serializers.CharField()
    actor_id = serializers.CharField()
    created_at = serializers.DateTimeField()


class LeaveAccountSerializer(serializers.Serializer):
    employee_id = serializers.CharField()
    leave_type = serializers.CharField()
    year = serializers.IntegerField()
    opening_balance = serializers.DecimalField(max_digits=7, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=7, decimal_places=2)
    source = serializers.CharField()
    ledger_balance = serializers.DecimalField(max_digits=7, decimal_places=2)
    reconciled = serializers.BooleanField()
    transactions = LeaveAccountTransactionSerializer(many=True)


class LeaveActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            "accept",
            "decline",
            "replace_substitute",
            "approve",
            "reject",
            "recommend",
            "not_recommend",
            "route",
            "withdraw",
            "review_resumption",
        ]
    )
    note = serializers.CharField(required=False, allow_blank=True)
    substitute_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class LeaveResumeSerializer(serializers.Serializer):
    actual_return_date = serializers.DateField()


class LeaveTransitionSerializer(serializers.Serializer):
    actor_id = serializers.CharField()
    action = serializers.CharField()
    from_state = serializers.CharField()
    to_state = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class LeaveExportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    employee_id = serializers.CharField()
    leave_type = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(required=False)
    status = serializers.CharField()
    workflow_state = serializers.CharField()
    decision_history = LeaveTransitionSerializer(many=True)


class LeaveOfflineRowSerializer(serializers.Serializer):
    external_id = serializers.CharField()
    employee_id = serializers.CharField()
    leave_type = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    sanction_reference = serializers.CharField()
    authority_id = serializers.CharField()
    source_reason = serializers.CharField()
    created_at = serializers.DateTimeField()


class LeaveOfflineResultSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()
    workflow_state = serializers.CharField()
    created = serializers.BooleanField()


class LeaveYearRunSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    exceptions = serializers.ListField(child=serializers.JSONField())


class LeaveAdminYearAccountSerializer(serializers.Serializer):
    employee_id = serializers.CharField()
    leave_type = serializers.CharField()
    year = serializers.IntegerField()
    opening_balance = serializers.DecimalField(max_digits=7, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=7, decimal_places=2)
    source = serializers.CharField()


class LeaveYearEndListSerializer(serializers.Serializer):
    runs = LeaveYearRunSerializer(many=True)
    accounts = LeaveAdminYearAccountSerializer(many=True)


class LeaveAdjustmentResultSerializer(serializers.Serializer):
    employee_id = serializers.CharField()
    leave_type = serializers.CharField()
    year = serializers.IntegerField()
    available_balance = serializers.DecimalField(max_digits=7, decimal_places=2)


class LeaveSLAProcessSerializer(serializers.Serializer):
    processed = serializers.IntegerField()


class LeaveIssuanceResultSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    issued = serializers.BooleanField()


class LeaveSLAConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveSLAConfig
        fields = "__all__"

    def validate(self, attrs):
        reminder = attrs.get("reminder_hours", getattr(self.instance, "reminder_hours", 0))
        escalation = attrs.get("escalation_hours", getattr(self.instance, "escalation_hours", 0))
        if reminder < 1 or escalation <= reminder:
            raise serializers.ValidationError(
                "Escalation must occur after a positive reminder threshold."
            )
        if attrs.get(
            "change_routing", getattr(self.instance, "change_routing", False)
        ) and not attrs.get(
            "escalation_actor_id", getattr(self.instance, "escalation_actor_id", "")
        ):
            raise serializers.ValidationError(
                {"escalation_actor_id": "Required when escalation changes task routing."}
            )
        return attrs
