"""Explicit review of historical trials and allocation of existing prepayments."""
from django import forms
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, AttendanceChargeRevision, Child, Group, Newcomer, Payment, Subscription, TrialCredit
from .trial_credit import credit_available_trial
from .views import log_action, role_required


class ReviewForm(forms.Form):
    charges_reviewed = forms.BooleanField(label="Начисления ниже проверены; суммы после изменения зачёта подтверждаю", required=False)
    subscription = forms.ModelChoiceField(queryset=Subscription.objects.none(), label="Абонемент", required=False)
    date = forms.DateField(label="Фактическая дата пробного", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    group = forms.ModelChoiceField(queryset=Group.objects.all(), label="Группа пробного")
    remove = forms.BooleanField(label="Снять зачёт (не восстанавливать автоматически)", required=False)
    reason = forms.CharField(label="Причина / подтверждение проверки", min_length=5, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}))
    version = forms.CharField(widget=forms.HiddenInput)


class AllocationForm(forms.Form):
    payment = forms.ModelChoiceField(queryset=Payment.objects.none(), label="Принятая предоплата")
    subscription = forms.ModelChoiceField(queryset=Subscription.objects.none(), label="Назначить абонементу")


class ChargeForm(forms.Form):
    attendance = forms.ModelChoiceField(queryset=Attendance.objects.none(), label="Занятие")
    amount = forms.DecimalField(label="Правильная сумма начисления, ₽", min_value=0, max_digits=10, decimal_places=2)
    reason = forms.CharField(label="Причина исправления", min_length=5, max_length=2000)
    version = forms.CharField(widget=forms.HiddenInput)


def charge_state(child):
    return [[row.pk, str(row.date), str(row.charge_amount), row.status, row.group_snapshot_id] for row in child.attendances.order_by("pk")]


def version(credit):
    return [credit.pk, credit.subscription_id, str(credit.date), credit.group_id, credit.is_void] if credit else None


@role_required(1)
def trial_management(request, pk):
    child = get_object_or_404(Child, pk=pk)
    credit = TrialCredit.objects.filter(child=child).select_related("subscription", "group").first()
    subscriptions = Subscription.objects.filter(child=child, cancelled_at__isnull=True, sessions_total__gt=0)
    trial = Newcomer.objects.filter(child=child, attended=True, lesson_cancelled=False, trial_at__isnull=False).order_by("trial_at").first()
    initial = {"date": credit.date if credit else timezone.localtime(trial.trial_at).date() if trial else None,
        "group": credit.group_id if credit else trial.group_id if trial else child.group_id,
        "subscription": credit.subscription_id if credit else None,
        "version": signing.dumps({"child": pk, "state": version(credit), "charges": charge_state(child)}, salt="trial.review")}
    action = request.POST.get("action")
    review = ReviewForm(request.POST if request.method == "POST" and action == "review" else None, initial=initial)
    allocation = AllocationForm(request.POST if request.method == "POST" and action == "allocate" else None)
    charge_form = ChargeForm(request.POST if request.method == "POST" and action == "charge" else None,
        initial={"version": signing.dumps({"child": pk, "charges": charge_state(child)}, salt="charge.review")})
    charge_form.fields["attendance"].queryset = child.attendances.all()
    review.fields["subscription"].queryset = subscriptions
    allocation.fields["subscription"].queryset = subscriptions
    allocation.fields["payment"].queryset = Payment.objects.filter(child=child, subscription__isnull=True, amount__gt=0, original_payment__isnull=True)
    for form in (review, allocation, charge_form):
        for field in form.fields.values():
            field.widget.attrs["class"] = "field" if not isinstance(field.widget, forms.CheckboxInput) else "h-4 w-4"
    active_form = review if action == "review" else allocation if action == "allocate" else charge_form if action == "charge" else None
    if request.method == "POST" and active_form and active_form.is_valid():
        with transaction.atomic():
            Child.objects.select_for_update().get(pk=pk)
            if action == "charge":
                data = charge_form.cleaned_data
                try:
                    payload = signing.loads(data["version"], salt="charge.review")
                except signing.BadSignature:
                    payload = {}
                mark = Attendance.objects.select_for_update().get(pk=data["attendance"].pk)
                if payload != {"child": pk, "charges": charge_state(child)}:
                    charge_form.add_error(None, "Отметки или суммы изменились. Обновите страницу и повторите сверку.")
                elif mark.charge_amount == data["amount"]:
                    charge_form.add_error("amount", "Сумма не изменилась.")
                elif mark.status != Attendance.Status.PRESENT and data["amount"] > 0:
                    charge_form.add_error("amount", "Положительное начисление возможно только за посещённое занятие.")
                else:
                    revision = AttendanceChargeRevision.objects.create(attendance=mark, child=child, attendance_number=mark.pk, attendance_date=mark.date, previous_amount=mark.charge_amount,
                        new_amount=data["amount"], reason=data["reason"], actor=request.user)
                    Attendance.objects.filter(pk=mark.pk).update(charge_amount=data["amount"])
                    log_action(request, "attendance.charge.correct", revision,
                        f"Занятие №{mark.pk}: {revision.previous_amount} → {revision.new_amount} ₽. {revision.reason}")
                    messages.success(request, "Начисление исправлено, прежняя сумма сохранена в истории. Баланс пересчитан; деньги не принимались и не возвращались.")
                    return redirect(request.path)
            elif action == "allocate":
                payment = Payment.objects.select_for_update().get(pk=allocation.cleaned_data["payment"].pk)
                sub = Subscription.objects.select_for_update().get(pk=allocation.cleaned_data["subscription"].pk)
                net = payment.amount + (payment.adjustments.aggregate(total=Sum("amount"))["total"] or 0)
                if payment.subscription_id or sub.cancelled_at or net <= 0:
                    allocation.add_error(None, "Предоплата уже распределена, возвращена или абонемент отменён. Обновите страницу.")
                else:
                    Payment.objects.filter(pk=payment.pk).update(subscription=sub)
                    payment.adjustments.update(subscription=sub)
                    log_action(request, "payment.allocate", payment, f"Предоплата №{payment.pk}, остаток {net} ₽ → абонемент №{sub.pk}. Суммы не изменены.")
                    credit_available_trial(pk)
                    messages.success(request, "Предоплата привязана. Новый платёж не создавался; баланс не изменился.")
                    return redirect(request.path)
            else:
                data = review.cleaned_data
                current = TrialCredit.objects.filter(child=child).first()
                try:
                    payload = signing.loads(data["version"], salt="trial.review")
                except signing.BadSignature:
                    payload = {}
                sub = Subscription.objects.select_for_update().get(pk=data["subscription"].pk) if data["subscription"] else None
                if payload != {"child": pk, "state": version(current), "charges": charge_state(child)}:
                    review.add_error(None, "Зачёт изменился после открытия формы. Обновите страницу и проверьте данные.")
                elif data["date"] > timezone.localdate():
                    review.add_error("date", "Пробное ещё не состоялось.")
                elif not data["remove"] and (not sub or sub.cancelled_at or sub.end_date < data["date"]):
                    review.add_error("subscription", "Выберите неотменённый абонемент, заканчивающийся не раньше пробного.")
                elif not data["remove"] and ((Payment.objects.filter(subscription=sub).aggregate(total=Sum("amount"))["total"] or 0) < sub.price or sub.price <= 0):
                    review.add_error("subscription", "Абонемент должен быть полностью оплачен связанными платежами.")
                elif not data["charges_reviewed"] and Attendance.objects.filter(child=child, date__gte=min(data["date"], current.date if current else data["date"]), charge_amount__gt=0).exists():
                    review.add_error(None, "После этой даты есть начисления за занятия в долг. Нужна финансовая сверка: зачёт не изменён, старые начисления автоматически не переписываются.")
                else:
                    before = version(current)
                    current = current or TrialCredit(child=child, created_by=request.user)
                    current.date, current.group = data["date"], data["group"]
                    current.subscription = None if data["remove"] else sub
                    current.is_void = data["remove"]
                    current.save()
                    log_action(request, "subscription.trial_review", current,
                        f"Зачёт {child}: {before} → {version(current)}. {data['reason']}")
                    messages.success(request, "Зачёт обновлён. Отметки посещений и платежи не изменялись.")
                    return redirect(request.path)
    return render(request, "crm/trial_management.html", {"child": child, "credit": credit, "review": review,
        "allocation": allocation, "charge_form": charge_form, "charges": child.attendances.filter(charge_amount__gt=0).select_related("group_snapshot"),
        "charge_revisions": AttendanceChargeRevision.objects.filter(child=child).select_related("attendance", "actor").order_by("-created_at"),
        "trial": trial, "title": "Пробное и предоплата", "page": "payments"})
