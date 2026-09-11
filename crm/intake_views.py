from datetime import date

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from . import views
from .models import Lead, ManagerTask, Newcomer, Notification


LEAD_RETURN_TASK_PREFIX = "Вернуться к заявке:"


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


def _applications_return_url(request):
    """Возвращает к текущим фильтрам, не переоткрывая модалку."""
    query = request.GET.copy()
    query.pop("edit", None)
    query.pop("create", None)
    url = reverse("applications")
    encoded = query.urlencode()
    return f"{url}?{encoded}" if encoded else url


def _lead_return_tasks(lead):
    return lead.manager_tasks.filter(
        title__startswith=LEAD_RETURN_TASK_PREFIX,
    )


def _close_lead(request):
    raw_until = (request.POST.get("closed_until") or "").strip()
    reason = (request.POST.get("closed_reason") or "").strip()

    try:
        closed_until = date.fromisoformat(raw_until)
    except (TypeError, ValueError):
        closed_until = None

    if closed_until is None:
        messages.error(request, "Укажите дату, когда нужно вернуться к заявке")
        return redirect(_applications_return_url(request))

    if closed_until < timezone.localdate():
        messages.error(request, "Дата возврата не может быть в прошлом")
        return redirect(_applications_return_url(request))

    if not reason:
        messages.error(request, "Укажите причину закрытия заявки")
        return redirect(_applications_return_url(request))

    with transaction.atomic():
        lead = get_object_or_404(
            Lead.objects.select_for_update(),
            pk=views._optional_pk(request.POST.get("lead_id")),
        )
        task = (
            _lead_return_tasks(lead)
            .select_for_update()
            .filter(is_done=False)
            .order_by("-created_at", "-pk")
            .first()
        )

        lead.status = Lead.Status.LOST
        lead.closed_until = closed_until
        lead.closed_reason = reason
        lead.save(
            update_fields=[
                "status",
                "closed_until",
                "closed_reason",
            ],
        )

        created = task is None
        if created:
            task = ManagerTask(
                lead=lead,
                created_by=request.user,
            )

        task.title = f"{LEAD_RETURN_TASK_PREFIX} {lead.full_name}"
        task.description = reason
        task.assignee = request.user
        task.due_date = closed_until
        task.is_done = False
        task.done_at = None
        task.completed_by = None
        task.completion_comment = ""
        if task.created_by_id is None:
            task.created_by = request.user
        task.save()

        views.notify_task(
            task,
            request.user,
            (
                Notification.Kind.TASK_CREATED
                if created
                else Notification.Kind.TASK_UPDATED
            ),
        )
        views.log_action(
            request,
            "lead.close",
            lead,
            (
                f"{lead.full_name}: закрыта до {closed_until:%d.%m.%Y}; "
                f"причина — {reason}"
            ),
        )

    messages.success(
        request,
        f"Заявка закрыта до {closed_until:%d.%m.%Y}; напоминание создано",
    )
    return redirect(_applications_return_url(request))


@login_required
def applications_page(request):
    action = request.POST.get("action", "save")

    if request.method == "POST" and action == "close_lead":
        return _close_lead(request)

    if request.method == "POST" and action == "quick_status":
        requested_status = (request.POST.get("status") or "").strip()
        status_labels = {
            Lead.Status.NEW.value: "Новая заявка",
            Lead.Status.CONTACTED.value: "В работе",
            Lead.Status.QUALIFIED.value: "Пробное",
            Lead.Status.LOST.value: "Закрыта",
        }

        if requested_status == Lead.Status.LOST.value:
            messages.error(
                request,
                "Для статуса «Закрыта» укажите дату возврата и причину",
            )
            return redirect(_applications_return_url(request))

        with transaction.atomic():
            lead = get_object_or_404(
                Lead.objects.select_for_update(),
                pk=views._optional_pk(request.POST.get("lead_id")),
            )
            has_paid = lead.newcomers.filter(
                child__payments__amount__gt=0,
            ).exists()

            if requested_status == "paid":
                if not has_paid:
                    messages.error(
                        request,
                        "Статус «Оплатил» определяется только фактической оплатой",
                    )
                    return redirect(_applications_return_url(request))
                new_status = Lead.Status.QUALIFIED.value
            elif requested_status in status_labels:
                if has_paid:
                    messages.error(
                        request,
                        "У оплаченной заявки статус «Оплатил» определяется автоматически",
                    )
                    return redirect(_applications_return_url(request))
                new_status = requested_status
            else:
                messages.error(request, "Недоступный статус заявки")
                return redirect(_applications_return_url(request))

            if lead.status != new_status:
                was_closed = lead.status == Lead.Status.LOST
                lead.status = new_status
                update_fields = ["status"]

                if was_closed:
                    lead.closed_until = None
                    lead.closed_reason = ""
                    update_fields.extend(
                        ["closed_until", "closed_reason"],
                    )
                    _lead_return_tasks(lead).select_for_update().filter(
                        is_done=False,
                    ).update(
                        is_done=True,
                        done_at=timezone.now(),
                        completed_by=request.user,
                        completion_comment="Заявка возвращена в работу",
                    )

                lead.save(update_fields=update_fields)
                views.log_action(
                    request,
                    "lead.quick_status",
                    lead,
                    (
                        f"{lead.full_name}: статус — "
                        f"{'Оплатил' if requested_status == 'paid' else status_labels[new_status]}"
                    ),
                )

        return redirect(_applications_return_url(request))

    if request.method == "POST" and action == "save":
        _set_form_target(request, Lead)
    else:
        _start_clean_create(request)

    return views.applications_page(request)


@login_required
def newcomers_page(request):
    action = request.POST.get("action", "save")

    if request.method == "POST" and action == "quick_flag":
        newcomer = get_object_or_404(
            Newcomer,
            pk=views._optional_pk(request.POST.get("newcomer_id")),
        )
        field = (request.POST.get("field") or "").strip()
        flag_labels = {
            "attended": "был на пробном",
            "lesson_cancelled": "занятие отменено",
            "documents_collected": "забрал документы",
            "trial_not_liked": "был, но не понравилось",
        }
        if field not in flag_labels:
            messages.error(request, "Недоступный быстрый признак")
            return redirect(request.get_full_path())

        enabled = request.POST.get("value") == "1"
        setattr(newcomer, field, enabled)
        update_fields = {field}

        if field == "attended":
            if enabled and newcomer.lesson_cancelled:
                newcomer.lesson_cancelled = False
                update_fields.add("lesson_cancelled")
            if not enabled and newcomer.trial_not_liked:
                newcomer.trial_not_liked = False
                update_fields.add("trial_not_liked")
        elif field == "lesson_cancelled" and enabled:
            if newcomer.attended:
                newcomer.attended = False
                update_fields.add("attended")
            if newcomer.trial_not_liked:
                newcomer.trial_not_liked = False
                update_fields.add("trial_not_liked")
        elif field == "trial_not_liked" and enabled:
            if not newcomer.attended:
                newcomer.attended = True
                update_fields.add("attended")
            if newcomer.lesson_cancelled:
                newcomer.lesson_cancelled = False
                update_fields.add("lesson_cancelled")

        newcomer.save(update_fields=sorted(update_fields))
        views.log_action(
            request,
            "newcomer.quick_flag",
            newcomer,
            (
                f"{newcomer.full_name}: {flag_labels[field]} "
                f"— {'да' if enabled else 'нет'}"
            ),
        )
        return redirect(request.get_full_path())

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
