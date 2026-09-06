from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import Child, Notification, Role, Subscription, user_role


def sync_subscription_notifications(user):
    if not user.is_authenticated or not user.is_staff:
        return

    today = timezone.localdate()
    limit = today + timedelta(days=7)

    subscriptions = (
        Subscription.objects
        .filter(
            is_active=True,
            child__status=Child.Status.ACTIVE,
            end_date__range=(today, limit),
        )
        .select_related("child")
    )

    active_keys = []

    for subscription in subscriptions:
        key = f"subscription_expiring:{subscription.pk}:{subscription.end_date.isoformat()}"
        active_keys.append(key)

        Notification.objects.get_or_create(
            recipient=user,
            event_key=key,
            defaults={
                "kind": Notification.Kind.SUBSCRIPTION_EXPIRING,
                "message": (
                    f"Абонемент {subscription.child} заканчивается "
                    f"{subscription.end_date:%d.%m.%Y}"
                ),
                "url": f"{reverse('payments')}?edit_subscription={subscription.pk}",
            },
        )

    Notification.objects.filter(
        recipient=user,
        kind=Notification.Kind.SUBSCRIPTION_EXPIRING,
        read_at__isnull=True,
    ).exclude(event_key__in=active_keys).update(read_at=timezone.now())


def crm_role_context(request):
    if not request.user.is_authenticated:
        return {
            "current_role": None,
            "is_boss": False,
            "is_senior": False,
            "notification_count": 0,
        }

    sync_subscription_notifications(request.user)

    role = user_role(request.user)

    return {
        "current_role": role,
        "is_boss": role == Role.BOSS,
        "is_senior": role in (Role.SENIOR, Role.BOSS),
        "notification_count": Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).count(),
    }