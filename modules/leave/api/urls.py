from rest_framework.routers import DefaultRouter

from .views import (
    LeaveAccountViewSet,
    LeaveBalanceViewSet,
    LeaveCalendarViewSet,
    LeaveInboxViewSet,
    LeaveOfflineViewSet,
    LeavePolicyViewSet,
    LeaveProfileViewSet,
    LeaveRequestViewSet,
    LeaveSLAViewSet,
    LeaveYearEndViewSet,
)

router = DefaultRouter()
router.register(r"balances", LeaveBalanceViewSet, basename="balance")
router.register(r"accounts", LeaveAccountViewSet, basename="account")
router.register(r"requests", LeaveRequestViewSet, basename="request")
router.register(r"inbox", LeaveInboxViewSet, basename="inbox")
router.register(r"profiles", LeaveProfileViewSet, basename="profile")
router.register(r"calendar", LeaveCalendarViewSet, basename="calendar")
router.register(r"policy", LeavePolicyViewSet, basename="policy")
router.register(r"offline-records", LeaveOfflineViewSet, basename="offline-record")
router.register(r"year-end", LeaveYearEndViewSet, basename="year-end")
router.register(r"sla", LeaveSLAViewSet, basename="sla")

urlpatterns = router.urls
