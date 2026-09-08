from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import (
    Child,
    Notification,
    Subscription,
    has_min_role,
    user_role,
)


def sync_subscription_notifications(user):
    if not user.is_authenticated or not user.is_staff:
        return

    today = timezone.localdate()
    limit = today + timedelta(days=7)

    # -------------------------
    # Заканчиваются в течение 7 дней
    # -------------------------
    subscriptions = (
        Subscription.objects
        .filter(
            is_active=True,
            child__status=Child.Status.ACTIVE,
            end_date__range=(today, limit),
        )
        .select_related("child")
    )

    expiring_keys = []

    for subscription in subscriptions:
        key = (
            f"subscription_expiring:"
            f"{subscription.pk}:"
            f"{subscription.end_date.isoformat()}"
        )

        expiring_keys.append(key)

        Notification.objects.get_or_create(
            recipient=user,
            event_key=key,
            defaults={
                "kind": Notification.Kind.SUBSCRIPTION_EXPIRING,
                "message": (
                    f"Абонемент {subscription.child} заканчивается "
                    f"{subscription.end_date:%d.%m.%Y}"
                ),
                "url": (
                    f"{reverse('payments')}"
                    f"?edit_subscription={subscription.pk}"
                ),
            },
        )

    Notification.objects.filter(
        recipient=user,
        kind=Notification.Kind.SUBSCRIPTION_EXPIRING,
        read_at__isnull=True,
    ).exclude(
        event_key__in=expiring_keys,
    ).update(
        read_at=timezone.now(),
    )

    # -------------------------
    # Уже закончились + есть долг
    # -------------------------
    expired_subscriptions = (
        Subscription.objects
        .filter(
            is_active=True,
            child__status=Child.Status.ACTIVE,
            end_date__lt=today,
        )
        .select_related("child")
        .order_by(
            "child_id",
            "-end_date",
            "-pk",
        )
    )

    debt_keys = []
    processed_children = set()

    for subscription in expired_subscriptions:
        child = subscription.child

        if child.pk in processed_children:
            continue

        processed_children.add(child.pk)

        debt = child.debt()

        if debt <= 0:
            continue

        key = (
            f"subscription_debt:"
            f"{subscription.pk}:"
            f"{subscription.end_date.isoformat()}"
        )

        debt_keys.append(key)

        Notification.objects.update_or_create(
            recipient=user,
            event_key=key,
            defaults={
                "kind": Notification.Kind.SUBSCRIPTION_DEBT,
                "message": (
                    f"{child} · абонемент закончился "
                    f"{subscription.end_date:%d.%m.%Y} · "
                    f"долг {debt:.2f} ₽"
                ),
                "url": reverse(
                    "child_card",
                    args=[child.pk],
                ),
            },
        )

    Notification.objects.filter(
        recipient=user,
        kind=Notification.Kind.SUBSCRIPTION_DEBT,
        read_at__isnull=True,
    ).exclude(
        event_key__in=debt_keys,
    ).update(
        read_at=timezone.now(),
    )


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
        "is_boss": has_min_role(request.user, 2),
        "is_senior": has_min_role(request.user, 1),
        "notification_count": Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).count(),
    }