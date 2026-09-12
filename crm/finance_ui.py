"""Search and paging for subscription history, independent of payment choices."""
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
from .models import Subscription
from .navigation import list_url


def subscription_history_context(request):
    query = request.GET.get("sub_q", "").strip()[:200]
    state = request.GET.get("sub_state", "all")
    if state not in {"all", "valid", "cancelled"}:
        state = "all"
    records = Subscription.objects.select_related("child__group", "group", "tariff").order_by("-start_date", "-pk")
    for word in query.split():
        records = records.filter(
            Q(child__last_name__icontains=word) | Q(child__first_name__icontains=word)
            | Q(child__patronymic__icontains=word) | Q(group__name__icontains=word)
            | Q(tariff__name__icontains=word)
            | Q(group__isnull=True, child__group__name__icontains=word)
        )
    if state != "all":
        records = records.filter(cancelled_at__isnull=state == "valid")
    page = Paginator(records, 30).get_page(request.GET.get("sub_page"))
    clean = request.GET.copy()
    for key in list(clean):
        if key in {"sub_q", "sub_state", "sub_page", "edit", "create", "next"} or key.startswith(("edit_", "new_")):
            clean.pop(key)
    reset_url = reverse("payments") + ("?" + clean.urlencode() if clean else "") + "#subscriptions"
    return {
        "subscriptions": page, "subscription_page": page,
        "sub_q": query, "sub_state": state,
        "subscription_history_open": any(key in request.GET for key in ("sub_q", "sub_state", "sub_page", "edit_subscription")),
        "subscription_filter_params": list(clean.items()),
        "subscription_reset_url": reset_url,
        "subscription_previous_url": list_url(request, "payments", sub_page=page.previous_page_number()) + "#subscriptions" if page.has_previous() else "",
        "subscription_next_url": list_url(request, "payments", sub_page=page.next_page_number()) + "#subscriptions" if page.has_next() else "",
    }
