from copy import copy

from django import forms
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Child


class RemoteOptions:
    def optgroups(self, name, value, attrs=None):
        # Keep field validation's full queryset; only limit HTML rendering.
        original = self.choices
        if hasattr(original, "field"):
            field = copy(original.field)
            ids = [int(item) for item in value if str(item).isdigit()]
            field.queryset = original.queryset.filter(pk__in=ids)
            self.choices = field.iterator(field)
        try:
            return super().optgroups(name, value, attrs)
        finally:
            self.choices = original


class RemoteChildSelect(RemoteOptions, forms.Select):
    pass


class RemoteChildrenSelect(RemoteOptions, forms.SelectMultiple):
    pass


@login_required
@require_GET
@never_cache
def athlete_lookup(request):
    from .forms import SubscriptionChildSelect
    from django.forms.models import ModelChoiceIteratorValue
    q = request.GET.get("q", "").strip()[:100]
    if len(q) < 2:
        return JsonResponse({"results": [], "more": False})
    children = Child.objects.select_related("group").prefetch_related("group_memberships")
    scope = request.GET.get("scope")
    if scope == "subscription":
        children = children.filter(status__in=(Child.Status.ACTIVE, Child.Status.TRIAL))
    elif scope == "competition":
        competition = request.GET.get("competition", "")
        children = children.filter(competition_entries__competition_id=int(competition) if competition.isdigit() else None).distinct()
    for word in q.split():
        condition = Q()
        # SQLite's case folding is ASCII-only; include common Russian name casing.
        for variant in {word, word.lower(), word.capitalize(), word.upper(), word.replace("е", "ё"), word.replace("ё", "е")}:
            condition |= Q(last_name__icontains=variant) | Q(first_name__icontains=variant) | Q(patronymic__icontains=variant)
        children = children.filter(condition)
    rows = list(children.order_by("last_name", "first_name", "pk")[:31])
    widget = SubscriptionChildSelect()
    results = []
    for child in rows[:30]:
        option = widget.create_option("child", ModelChoiceIteratorValue(child.pk, child), str(child), False, 0)
        results.append({"id": child.pk, "label": f"{child} · {child.get_status_display()}",
            "attrs": {**option["attrs"], "data-child-status": child.status}})
    return JsonResponse({"results": results, "more": len(rows) > 30})
