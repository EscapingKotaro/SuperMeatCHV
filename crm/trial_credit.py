"""Credit one confirmed trial to a paid subscription without duplicating attendance."""
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Attendance, AuditEvent, Child, Newcomer, Payment, TrialCredit


def credit_paid_trial(subscription, *, child=None, actor=None, was_trial=False, trial_from=None):
    child_id = subscription.child_id if subscription else child.pk if child else None
    if child_id is None:
        return None
    with transaction.atomic():
        child = Child.objects.select_for_update().get(pk=child_id)
        credit = TrialCredit.objects.filter(child=child).first()
        if credit and (credit.subscription_id or credit.is_void):
            return None
        today = timezone.localdate()
        newcomer = Newcomer.objects.filter(child=child, attended=True, lesson_cancelled=False,
            trial_at__isnull=False, trial_at__date__lte=today).order_by("trial_at", "pk").first()
        if credit:
            trial_date, group_id = credit.date, credit.group_id
        elif newcomer:
            trial_date = timezone.localtime(newcomer.trial_at).date()
            group_id = newcomer.group_id
        elif was_trial:
            marks = Attendance.objects.filter(child=child, status="present", date__lte=today)
            if trial_from:
                marks = marks.filter(date__gte=trial_from)
            mark = marks.order_by("date", "pk").first()
            if not mark:
                return None
            trial_date = mark.date
            group_id = mark.group_snapshot_id or child.group_id
        else:
            return None
        if not credit:
            credit = TrialCredit.objects.create(child=child, date=trial_date, group_id=group_id, created_by=actor)
        if not subscription or subscription.cancelled_at or subscription.sessions_total == 0 or trial_date > subscription.end_date:
            return None
        net = Payment.objects.filter(subscription=subscription).aggregate(total=Sum("amount"))["total"] or 0
        if net <= 0 or net < subscription.price:
            return None
        if Attendance.objects.filter(child=child, date__gte=trial_date, charge_amount__gt=0).exists():
            return None
        credit.subscription = subscription
        credit.save(update_fields=["subscription"])
        AuditEvent.objects.create(actor=actor, action="subscription.trial_credit", object_type="Subscription",
            object_id=str(subscription.pk), description=f"Пробное {trial_date:%d.%m.%Y} зачтено в абонемент №{subscription.pk}: {child}")
        return credit


def credit_available_trial(child_id):
    """Late confirmation: never guess between multiple paid subscriptions."""
    from .models import Subscription
    with transaction.atomic():
        child = Child.objects.select_for_update().get(pk=child_id)
        if TrialCredit.objects.filter(child=child).filter(Q(subscription__isnull=False) | Q(is_void=True)).exists():
            return None
        candidates = []
        for sub in Subscription.objects.filter(child=child, cancelled_at__isnull=True, sessions_total__gt=0).order_by("start_date", "pk"):
            net = Payment.objects.filter(subscription=sub).aggregate(total=Sum("amount"))["total"] or 0
            if net > 0 and net >= sub.price:
                candidates.append(sub)
        if len(candidates) == 1:
            return credit_paid_trial(candidates[0], was_trial=child.status == Child.Status.TRIAL, trial_from=child.trial_from)
    return None
