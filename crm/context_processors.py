from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Attendance, Child, Newcomer, Notification, Payment, Subscription, has_min_role, user_role
from .navigation import current_list_url


def _sync_events(user, scope, desired):
    """Пакетная синхронизация без запросов на каждое событие."""
    existing = {item.event_key: item for item in Notification.objects.filter(recipient=user).filter(scope).filter(Q(resolved_at__isnull=True) | Q(event_key__in=desired))}
    now = timezone.now()
    created, changed = [], []
    for key, values in desired.items():
        item = existing.get(key)
        if item is None:
            created.append(Notification(recipient=user, event_key=key, **values))
            continue
        if item.resolved_at is not None or any(getattr(item, field) != value for field, value in values.items()):
            # Повторно возникшая проблема снова непрочитана.
            if item.resolved_at is not None:
                item.read_at = None
            item.resolved_at = None
            for field, value in values.items():
                setattr(item, field, value)
            changed.append(item)
    Notification.objects.bulk_create(created, ignore_conflicts=True)
    if changed:
        Notification.objects.bulk_update(changed, ["kind", "message", "url", "resolved_at", "read_at"])
    unresolved_ids = [item.pk for key, item in existing.items() if key not in desired and item.resolved_at is None]
    if unresolved_ids:
        Notification.objects.filter(pk__in=unresolved_ids).update(resolved_at=now)


def sync_subscription_notifications(user):
    if not user.is_authenticated or not user.is_staff:
        return
    today = timezone.localdate()
    subscriptions = list(Subscription.objects.filter(
        is_active=True, cancelled_at__isnull=True, child__status=Child.Status.ACTIVE,
        end_date__lte=today + timedelta(days=7),
    ).select_related("child").order_by("child_id", "-end_date", "-pk"))
    expired_ids = {sub.child_id for sub in subscriptions if sub.end_date < today}
    def totals(model, field, **filters):
        return dict(model.objects.filter(child_id__in=expired_ids, **filters).values("child_id").annotate(total=Sum(field)).values_list("child_id", "total")) if expired_ids else {}
    charges = totals(Subscription, "price", cancelled_at__isnull=True)
    attendance = totals(Attendance, "charge_amount")
    payments = totals(Payment, "amount")
    desired, seen = {}, set()
    for sub in subscriptions:
        if sub.end_date >= today:
            key = f"subscription_expiring:{sub.pk}:{sub.end_date.isoformat()}"
            desired[key] = {"kind": Notification.Kind.SUBSCRIPTION_EXPIRING,
                            "message": f"Абонемент {sub.child} заканчивается {sub.end_date:%d.%m.%Y}",
                            "url": f"{reverse('payments')}?edit_subscription={sub.pk}"}
        elif sub.child_id not in seen:
            seen.add(sub.child_id)
            debt = (charges.get(sub.child_id) or Decimal(0)) + (attendance.get(sub.child_id) or Decimal(0)) - (payments.get(sub.child_id) or Decimal(0))
            if debt > 0:
                key = f"subscription_debt:{sub.pk}:{sub.end_date.isoformat()}"
                desired[key] = {"kind": Notification.Kind.SUBSCRIPTION_DEBT,
                                "message": f"{sub.child} · абонемент закончился {sub.end_date:%d.%m.%Y} · долг {debt:.2f} ₽",
                                "url": reverse("child_card", args=[sub.child_id])}
    _sync_events(user, Q(kind__in=[Notification.Kind.SUBSCRIPTION_EXPIRING, Notification.Kind.SUBSCRIPTION_DEBT]), desired)


def sync_today_trials(user):
    if not user.is_authenticated or not user.is_staff:
        return
    today = timezone.localdate()
    desired = {f"trial_today:{item.pk}:{today}": {
        "kind": Notification.Kind.TRIAL_SCHEDULED,
        "message": f"Сегодня пробное: {item.full_name}",
        "url": reverse("newcomers") + f"?edit={item.pk}",
    } for item in Newcomer.objects.filter(trial_at__date=today, attended=False, lesson_cancelled=False)}
    _sync_events(user, Q(event_key__startswith="trial_today:"), desired)
    Notification.objects.filter(recipient=user, task__is_done=True, resolved_at__isnull=True,
                                kind__in=[Notification.Kind.TASK_CREATED, Notification.Kind.TASK_UPDATED, Notification.Kind.TASK_REOPENED]).update(resolved_at=timezone.now())


def crm_role_context(request):
    if not request.user.is_authenticated:
        return {"current_role": None, "is_boss": False, "is_senior": False, "notification_count": 0}
    return_url = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(return_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return_url = ""
    return {
        "workflow_return_url": return_url,
        "workflow_list_url": current_list_url(request),
        "current_role": user_role(request.user),
        "is_boss": has_min_role(request.user, 2),
        "is_senior": has_min_role(request.user, 1),
        "notification_count": Notification.objects.filter(recipient=request.user, read_at__isnull=True, resolved_at__isnull=True).count(),
    }
