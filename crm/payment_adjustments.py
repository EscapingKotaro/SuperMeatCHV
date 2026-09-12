"""Append-only payment reversals. All amounts still use the shared payment ledger."""
import hashlib
import json
import uuid
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Child, Payment
from .views import log_action, role_required

SALT = "crm.payment.adjustment.v1"


class AdjustmentForm(forms.Form):
    kind = forms.ChoiceField(label="Операция", choices=(("refund", "Возврат денег"), ("correction", "Сторно ошибочной оплаты")))
    amount = forms.DecimalField(label="Сумма", min_value=Decimal("0.01"), max_digits=10, decimal_places=2)
    date = forms.DateField(label="Дата операции", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    reason = forms.CharField(label="Причина", min_length=5, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
    token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "field"


def remaining(payment):
    return payment.amount + (payment.adjustments.aggregate(total=Sum("amount"))["total"] or Decimal("0"))


@role_required(1)
def adjust_payment(request, pk):
    original = get_object_or_404(Payment.objects.select_related("child", "subscription"), pk=pk, amount__gt=0, original_payment__isnull=True)
    token = signing.dumps({"user": request.user.pk, "payment": pk, "key": str(uuid.uuid4())}, salt=SALT)
    form = AdjustmentForm(request.POST if request.method == "POST" else None, initial={"date": timezone.localdate(), "token": token})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            payload = signing.loads(data["token"], salt=SALT)
            key = uuid.UUID(payload["key"])
            if payload["user"] != request.user.pk or payload["payment"] != pk:
                raise ValueError()
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            form.add_error(None, "Недействительный ключ операции. Откройте форму заново из истории оплат.")
        else:
            digest = hashlib.sha256(json.dumps({name: str(data[name]) for name in ("kind", "amount", "date", "reason")}, sort_keys=True).encode()).hexdigest()
            with transaction.atomic():
                # Match the child-first order used by payment creation.
                Child.objects.select_for_update().get(pk=original.child_id)
                original = Payment.objects.select_for_update().get(pk=pk)
                existing = Payment.objects.filter(submission_key=key).first()
                available = remaining(original)
                if existing:
                    if existing.original_payment_id == pk and existing.submission_hash == digest:
                        messages.info(request, "Операция уже проведена. Повторная запись не создана.")
                        return redirect(reverse("payment_history") + "?month=" + existing.date.strftime("%Y-%m"))
                    form.add_error(None, "Этот ключ уже использован с другими данными. Откройте новую форму.")
                elif data["date"] < original.date or data["date"] > timezone.localdate():
                    form.add_error("date", "Дата должна быть не раньше исходной оплаты и не позже сегодня.")
                elif data["amount"] > available:
                    form.add_error("amount", f"Доступно для возврата или сторно: {available:.2f} ₽.")
                else:
                    entry = Payment.objects.create(child_id=original.child_id, subscription_id=original.subscription_id,
                        original_payment=original, operation_kind=data["kind"], reason=data["reason"],
                        amount=-data["amount"], date=data["date"], created_by=request.user,
                        submission_key=key, submission_hash=digest)
                    log_action(request, "payment." + data["kind"], entry,
                        f"{entry.get_operation_kind_display()} №{original.pk}: {data['amount']} ₽. {data['reason']}")
                    messages.success(request, "Операция записана. Баланс и выручка пересчитаны. Абонемент и группа не изменены.")
                    return redirect(reverse("payment_history") + "?month=" + entry.date.strftime("%Y-%m"))
    return render(request, "crm/payment_adjustment.html", {"form": form, "original": original,
        "remaining": remaining(original), "title": "Возврат / исправление оплаты", "page": "payments"})
