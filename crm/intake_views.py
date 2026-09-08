from django.shortcuts import get_object_or_404

from . import views
from .models import Lead, Newcomer


def _set_edit_target(request, model):
    query = request.GET.copy()
    query.pop("edit", None)

    editing_id = (request.POST.get("editing_id") or "").strip()
    if editing_id:
        get_object_or_404(model, pk=editing_id)
        query["edit"] = editing_id

    request.GET = query


def _start_clean_create(request):
    if request.GET.get("create") != "1":
        return

    query = request.GET.copy()
    query.pop("edit", None)
    request.GET = query


def applications_page(request):
    if (
        request.method == "POST"
        and request.POST.get("action", "save") == "save"
    ):
        _set_edit_target(request, Lead)
    else:
        _start_clean_create(request)

    return views.applications_page(request)


def newcomers_page(request):
    if (
        request.method == "POST"
        and request.POST.get("action", "save") == "save"
    ):
        _set_edit_target(request, Newcomer)
    else:
        _start_clean_create(request)

    return views.newcomers_page(request)
