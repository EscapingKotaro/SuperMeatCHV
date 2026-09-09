from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from . import views
from .models import Lead, Newcomer


def _set_form_target(request, model):
    """
    Разделяет явное создание и редактирование.

    Новые формы передают form_mode + editing_id.
    Старые POST-запросы без этих полей сохраняют поддержку ?edit=<id>,
    чтобы не ломать существующие сценарии и интеграции.
    """
    form_mode = (request.POST.get("form_mode") or "").strip()
    editing_id = (request.POST.get("editing_id") or "").strip()
    query = request.GET.copy()

    if form_mode == "create":
        query.pop("edit", None)

    elif editing_id:
        target_id = views._optional_pk(editing_id)
        get_object_or_404(model, pk=target_id)
        query["edit"] = str(target_id)

    elif form_mode == "edit":
        # Явный edit без цели не должен случайно создать новую запись
        # или использовать устаревший ?edit= из адресной строки.
        query.pop("edit", None)

    # Если form_mode/editing_id отсутствуют, оставляем GET как есть:
    # это обратная совместимость со старым POST на ?edit=<id>.
    request.GET = query


def _start_clean_create(request):
    if request.GET.get("create") != "1":
        return

    query = request.GET.copy()
    query.pop("edit", None)
    request.GET = query


@login_required
def applications_page(request):
    if (
        request.method == "POST"
        and request.POST.get("action", "save") == "save"
    ):
        _set_form_target(request, Lead)
    else:
        _start_clean_create(request)

    return views.applications_page(request)


@login_required
def newcomers_page(request):
    action = request.POST.get("action", "save")

    if request.method == "POST" and action == "convert":
        newcomer = get_object_or_404(
            Newcomer,
            pk=request.POST.get("newcomer_id"),
        )
        if not newcomer.child_id and newcomer.group_id is None:
            messages.error(
                request,
                "Сначала назначьте новичку группу",
            )
            return redirect("newcomers")

    if request.method == "POST" and action == "save":
        _set_form_target(request, Newcomer)
    else:
        _start_clean_create(request)

    return views.newcomers_page(request)
