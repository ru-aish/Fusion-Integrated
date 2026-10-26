from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from .models import LeaveBalance, LeaveRequest, leave_days


class LeaveBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveBalance
        fields = ['employee_id', 'leave_type', 'balance', 'last_updated']

class LeaveRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = ['id', 'employee_id', 'leave_type', 'start_date', 'end_date', 'reason',
                  'half_day', 'station_leave', 'station_leave_details', 'status',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'employee_id', 'status', 'created_at', 'updated_at']

    def validate(self, attrs):
        employee_id = str(self.context['request'].principal.user_id)
        leave_type = attrs.get('leave_type', getattr(self.instance, 'leave_type', None))
        start = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        half_day = attrs.get('half_day', getattr(self.instance, 'half_day', 'none'))
        if start and end and end < start:
            raise serializers.ValidationError({
                'end_date': 'End date must be on or after start date.'})
        if half_day != 'none' and (leave_type != 'CL' or start != end):
            raise serializers.ValidationError({
                'half_day': 'Half-day requests are supported only for one-day Casual Leave.'})
        if attrs.get('station_leave') and not attrs.get('station_leave_details', '').strip():
            raise serializers.ValidationError({
                'station_leave_details': 'Details are required when Station Leave applies.'})
        if not start or not end or not leave_type:
            return attrs

        overlap = LeaveRequest.objects.filter(
            employee_id=employee_id,
            status__in=['pending', 'approved'],
            start_date__lte=end, end_date__gte=start,
        )
        if self.instance:
            overlap = overlap.exclude(pk=self.instance.pk)
        # The only same-date exception is opposite CL half-days.
        if half_day != 'none' and start == end:
            overlap = overlap.exclude(
                leave_type='CL', start_date=start, end_date=end,
                half_day=('second' if half_day == 'first' else 'first'),
            )
        if overlap.exists():
            raise serializers.ValidationError({
                'start_date': 'This request overlaps pending or approved leave.'})

        requested_days = Decimal(str(leave_days(leave_type, start, end, half_day)))
        balance = LeaveBalance.objects.filter(
            employee_id=employee_id, leave_type=leave_type).first()
        if balance is None:
            raise serializers.ValidationError({
                'leave_type': 'No leave balance is provisioned for this category.'})
        already_committed = Decimal('0')
        for request in LeaveRequest.objects.filter(
            employee_id=employee_id, leave_type=leave_type, status__in=['pending', 'approved']
        ):
            already_committed += Decimal(str(request.duration()))
        if already_committed + requested_days > balance.balance:
            raise serializers.ValidationError({
                'leave_type': 'Insufficient available leave balance.'})
        return attrs

    def create(self, validated_data):
        # Serialize competing submissions against the employee/category account,
        # then recheck commitments while holding the row lock.
        employee_id = str(self.context['request'].principal.user_id)
        category = validated_data['leave_type']
        with transaction.atomic():
            LeaveBalance.objects.select_for_update().get(
                employee_id=employee_id, leave_type=category)
            self.validate(validated_data)
            return super().create(validated_data)
