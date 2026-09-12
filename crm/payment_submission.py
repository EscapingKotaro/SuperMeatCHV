"""Signed, per-user payment submissions with durable replay detection."""
import hashlib
import json
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.shortcuts import redirect

from .models import Payment
from .navigation import list_url

SALT = "crm.payment.submission.v1"


def issue_token(user_id):
    return signing.dumps({"user": user_id, "key": str(uuid.uuid4())}, salt=SALT)


def prepare_submission(request):
    if getattr(request, "_payment_submission_checked", False):
        return None
    request._payment_submission_checked = True
    request.payment_token = issue_token(request.user.pk)
    if request.method != "POST" or request.POST.get("action", "payment") != "payment":
        return None
    token = request.POST.get("submission_token", "")
    try:
        payload = signing.loads(token, salt=SALT)
        key = uuid.UUID(payload["key"])
        if payload["user"] != request.user.pk:
            raise ValueError("user")
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        request.payment_submission_error = "Форма оплаты устарела или не содержит ключ операции. Проверьте данные и отправьте форму ещё раз."
        return None
    request.payment_token = token
    fields = ("child_id", "amount", "date", "subscription_id", "working_group_id")
    digest = hashlib.sha256(json.dumps({field: request.POST.get(field, "").strip() for field in fields}, sort_keys=True).encode()).hexdigest()
    # All submission paths use an enclosing transaction. This serializes replays
    # from the same actor, including requests targeting different children.
    get_user_model().objects.select_for_update().get(pk=request.user.pk)
    existing = Payment.objects.filter(submission_key=key).first()
    if existing:
        if existing.submission_hash != digest:
            request.payment_submission_error = "Эта операция уже проведена с другими данными. Для отдельной оплаты откройте новую форму."
            return None
        messages.info(request, f"Оплата №{existing.pk} уже сохранена. Повторная запись не создана.")
        return redirect(list_url(request, "payments"))
    request.payment_submission_key = key
    request.payment_submission_hash = digest
    return None
