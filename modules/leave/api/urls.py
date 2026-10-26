from rest_framework.routers import DefaultRouter

from .views import (
    LeaveBalanceViewSet,
    LeaveCalendarViewSet,
    LeaveInboxViewSet,
    LeavePolicyViewSet,
    LeaveProfileViewSet,
    LeaveRequestViewSet,
)

router = DefaultRouter()
router.register(r"balances", LeaveBalanceViewSet, basename="balance")
router.register(r"requests", LeaveRequestViewSet, basename="request")
router.register(r"inbox", LeaveInboxViewSet, basename="inbox")
router.register(r"profiles", LeaveProfileViewSet, basename="profile")
router.register(r"calendar", LeaveCalendarViewSet, basename="calendar")
router.register(r"policy", LeavePolicyViewSet, basename="policy")

urlpatterns = router.urls
