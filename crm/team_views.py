"""Trainer and group management views.

This module is deliberately separate from the main CRM views module so the
team-management subsystem can evolve without adding more unrelated code to
crm.views.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import GroupForm, ScheduleSlotFormSet, TrainerForm
from .models import Child, Group, Trainer
from .views import _optional_pk, log_action


# ==================== КЛИЕНТЫ ====================

def _completed_age(child, today):
    if child.birth_date:
        return (
            today.year
            - child.birth_date.year
            - (
                (today.month, today.day)
                < (child.birth_date.month, child.birth_date.day)
            )
        )
    if child.birth_year:
        return max(0, today.year - child.birth_year)
    return None


def _age_filter_value(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 120 else None


@login_required
def clients_page(request):
    """Рабочий реестр действующих и неактивных спортсменов."""
    today = timezone.localdate()
    query = (request.GET.get("q") or "").strip()
    letter = (request.GET.get("letter") or "").strip().upper()[:1]
    if not letter.isalpha():
        letter = ""

    state = request.GET.get("state", "active")
    if state not in {"active", "inactive", "all"}:
        state = "active"

    trainer_id = _optional_pk(request.GET.get("trainer"))
    group_id = _optional_pk(request.GET.get("group"))

    debt_filter = request.GET.get("debt", "all")
    if debt_filter not in {"all", "yes", "no"}:
        debt_filter = "all"

    alerts_filter = request.GET.get("alerts", "all")
    if alerts_filter not in {"all", "yes", "no"}:
        alerts_filter = "all"

    age_from = _age_filter_value(request.GET.get("age_from"))
    age_to = _age_filter_value(request.GET.get("age_to"))
    if (
        age_from is not None
        and age_to is not None
        and age_from > age_to
    ):
        age_from, age_to = age_to, age_from

    sort = request.GET.get("sort", "az")
    if sort not in {"az", "za"}:
        sort = "az"

    children = (
        Child.objects
        .exclude(status=Child.Status.TRIAL)
        .select_related("group__trainer")
        .prefetch_related(
            "subscriptions",
            "payments",
            "attendances",
            "group_memberships__group__trainer",
        )
    )

    if state == "active":
        children = children.filter(status=Child.Status.ACTIVE)
    elif state == "inactive":
        children = children.filter(
            status__in=(Child.Status.ARCHIVED, Child.Status.LOST),
        )

    for term in query.split():
        children = children.filter(
            Q(last_name__icontains=term)
            | Q(first_name__icontains=term)
            | Q(patronymic__icontains=term)
            | Q(parent_name__icontains=term)
            | Q(parent_phone__icontains=term)
            | Q(second_parent_name__icontains=term)
            | Q(second_parent_phone__icontains=term)
        )

    if letter:
        children = children.filter(last_name__istartswith=letter)

    if trainer_id is not None:
        children = children.filter(
            Q(group__trainer_id=trainer_id)
            | Q(
                group_memberships__group__trainer_id=trainer_id,
                group_memberships__archived_at__isnull=True,
            )
        )

    if group_id is not None:
        children = children.filter(
            Q(group_id=group_id)
            | Q(
                group_memberships__group_id=group_id,
                group_memberships__archived_at__isnull=True,
            )
        )

    ordering = (
        ("last_name", "first_name", "patronymic", "pk")
        if sort == "az"
        else ("-last_name", "-first_name", "-patronymic", "-pk")
    )
    children = children.distinct().order_by(*ordering)

    rows = []
    for child in children:
        age = _completed_age(child, today)
        debt = child.debt()
        alerts = child.document_alerts(today)

        if age_from is not None and (age is None or age < age_from):
            continue
        if age_to is not None and (age is None or age > age_to):
            continue
        if debt_filter == "yes" and debt <= 0:
            continue
        if debt_filter == "no" and debt > 0:
            continue
        if alerts_filter == "yes" and not alerts:
            continue
        if alerts_filter == "no" and alerts:
            continue

        client_groups = []
        seen_group_ids = set()
        if child.group_id:
            client_groups.append(child.group)
            seen_group_ids.add(child.group_id)

        for membership in child.group_memberships.all():
            if (
                membership.archived_at is None
                and membership.group_id not in seen_group_ids
            ):
                client_groups.append(membership.group)
                seen_group_ids.add(membership.group_id)

        client_trainers = []
        seen_trainer_ids = set()
        for group in client_groups:
            if group.trainer_id not in seen_trainer_ids:
                client_trainers.append(group.trainer)
                seen_trainer_ids.add(group.trainer_id)

        rows.append({
            "child": child,
            "age": age,
            "debt": debt,
            "alert_count": len(alerts),
            "groups": client_groups,
            "trainers": client_trainers,
        })

    context = {
        "client_registry": True,
        "client_rows": rows,
        "client_count": len(rows),
        "client_query": query,
        "client_letter": letter,
        "client_state": state,
        "client_trainer_id": trainer_id,
        "client_group_id": group_id,
        "client_debt": debt_filter,
        "client_alerts": alerts_filter,
        "client_age_from": age_from,
        "client_age_to": age_to,
        "client_sort": sort,
        "filter_trainers": Trainer.objects.order_by("full_name"),
        "filter_groups": (
            Group.objects
            .select_related("trainer")
            .order_by("trainer__full_name", "name")
        ),
        "title": "Клиенты",
        "subtitle": "Действующие и неактивные спортсмены",
        "page": "clients",
    }
    return render(request, "crm/search.html", context)


# ==================== ТРЕНЕРЫ ====================

def _trainer_list_data(request):
    state = request.GET.get("state", "active")
    if state not in {"active", "archive", "all"}:
        state = "active"

    base = Trainer.objects.prefetch_related("groups")
    counts = Trainer.objects.aggregate(
        active=Count("pk", filter=Q(is_active=True)),
        archive=Count("pk", filter=Q(is_active=False)),
    )
    trainers = base
    if state == "active":
        trainers = trainers.filter(is_active=True)
    elif state == "archive":
        trainers = trainers.filter(is_active=False)

    return (
        state,
        trainers.order_by("full_name"),
        counts["active"],
        counts["archive"],
    )


@login_required
def trainer_list_view(request):
    """Список тренеров, архив и встроенное редактирование."""
    state, trainers, active_count, archive_count = _trainer_list_data(request)

    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"archive", "restore"}:
            trainer = get_object_or_404(
                Trainer,
                pk=_optional_pk(request.POST.get("trainer_id")),
            )
            make_active = action == "restore"
            if trainer.is_active != make_active:
                trainer.is_active = make_active
                trainer.save(update_fields=["is_active"])
                log_action(
                    request,
                    f"trainer.{action}",
                    trainer,
                    (
                        f"Тренер {trainer.full_name} "
                        f"{'восстановлен из архива' if make_active else 'перенесён в архив'}"
                    ),
                )
            messages.success(
                request,
                (
                    f"Тренер {trainer.full_name} восстановлен"
                    if make_active
                    else f"Тренер {trainer.full_name} добавлен в архив"
                ),
            )
            target_state = "active" if make_active else "archive"
            return redirect(f"{reverse('trainer_list')}?state={target_state}")

    editing_id = _optional_pk(request.GET.get("edit"))
    if editing_id is not None or request.GET.get("create"):
        request._inline_trainer = True
        return trainer_edit_view(request, editing_id) if editing_id is not None else trainer_create_view(request)
    context = {
        'trainers': trainers,
        'trainer_state': state,
        'trainer_active_count': active_count,
        'trainer_archive_count': archive_count,
        'trainer_total_count': active_count + archive_count,
        'title': 'Тренеры',
        'subtitle': 'Управление тренерским составом',
        'page': 'trainers'
    }
    return render(request, 'crm/trainers.html', context)

@login_required
def trainer_create_view(request):
    """Создание тренера"""
    if request.method != 'POST' and not getattr(request, "_inline_trainer", False):
        return redirect(f"{reverse('trainer_list')}?create=1")

    if request.method == 'POST':
        form = TrainerForm(request.POST)
        if form.is_valid():
            trainer = form.save()
            messages.success(request, f'Тренер {trainer.full_name} добавлен')
            return redirect('trainer_list')
    else:
        form = TrainerForm()

    context = {
        'form': form,
        'title': 'Новый тренер',
        'page': 'trainers'
    }
    state, trainers, active_count, archive_count = _trainer_list_data(request)
    context["form_title"] = context["title"]
    context["title"] = "Тренеры"
    context["trainers"] = trainers
    context["trainer_state"] = state
    context["trainer_active_count"] = active_count
    context["trainer_archive_count"] = archive_count
    context["trainer_total_count"] = active_count + archive_count
    return render(request, "crm/trainers.html", context)

@login_required
def trainer_edit_view(request, pk):
    """Редактирование тренера"""
    trainer = get_object_or_404(Trainer, pk=pk)
    if request.method != 'POST' and not getattr(request, "_inline_trainer", False):
        return redirect(f"{reverse('trainer_list')}?edit={trainer.pk}")

    if request.method == 'POST':
        form = TrainerForm(request.POST, instance=trainer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Данные тренера обновлены')
            return redirect('trainer_list')
    else:
        form = TrainerForm(instance=trainer)

    context = {
        'form': form,
        'trainer': trainer,
        'title': f'Редактирование: {trainer.full_name}',
        'page': 'trainers'
    }
    state, trainers, active_count, archive_count = _trainer_list_data(request)
    context["form_title"] = context["title"]
    context["title"] = "Тренеры"
    context["trainers"] = trainers
    context["trainer_state"] = state
    context["trainer_active_count"] = active_count
    context["trainer_archive_count"] = archive_count
    context["trainer_total_count"] = active_count + archive_count
    return render(request, "crm/trainers.html", context)

@login_required
def trainer_delete_view(request, pk):
    """Legacy URL: тренера переводим в архив вместо удаления истории."""
    trainer = get_object_or_404(Trainer, pk=pk)
    if request.method == "POST":
        if trainer.is_active:
            trainer.is_active = False
            trainer.save(update_fields=["is_active"])
            log_action(
                request,
                "trainer.archive",
                trainer,
                f"Тренер {trainer.full_name} перенесён в архив",
            )
        messages.success(request, f"Тренер {trainer.full_name} добавлен в архив")
        return redirect("trainer_list")

    messages.warning(
        request,
        "Удаление тренеров отключено: используйте архив, чтобы сохранить историю.",
    )
    return redirect("trainer_list")


# ==================== ГРУППЫ ====================

@login_required
def group_list_view(request):
    """Список групп и встроенное редактирование."""
    editing_id = _optional_pk(request.GET.get("edit"))
    if editing_id is not None or request.GET.get("create"):
        request._inline_group = True
        return group_edit_view(request, editing_id) if editing_id is not None else group_create_view(request)
    groups = Group.objects.select_related('trainer').prefetch_related('schedule', 'children', 'subscription_tariffs').order_by('trainer__full_name', 'trainer_id', 'name')
    context = {
        'groups': groups,
        'title': 'Группы',
        'subtitle': 'Управление группами и расписанием',
        'page': 'groups'
    }
    return render(request, 'crm/groups.html', context)

@login_required
def group_create_view(request):
    """Создание группы с расписанием"""
    if request.method != 'POST' and not getattr(request, "_inline_group", False):
        return redirect(f"{reverse('group_list')}?create=1")

    if request.method == 'POST':
        group_form = GroupForm(request.POST)
        slot_formset = ScheduleSlotFormSet(request.POST)

        if group_form.is_valid() and slot_formset.is_valid():
            group = group_form.save()
            slot_formset.instance = group
            slot_formset.save()
            messages.success(request, f'Группа "{group.name}" создана')
            return redirect('group_list')
    else:
        group_form = GroupForm()
        slot_formset = ScheduleSlotFormSet()

    context = {
        'group_form': group_form,
        'slot_formset': slot_formset,
        'title': 'Новая группа',
        'page': 'groups'
    }
    context["form_title"] = context["title"]
    context["title"] = "Группы"
    context["groups"] = Group.objects.select_related("trainer").prefetch_related("schedule", "children", "subscription_tariffs").order_by("trainer__full_name", "trainer_id", "name")
    return render(request, "crm/groups.html", context)

@login_required
def group_edit_view(request, pk):
    """Редактирование группы с расписанием"""
    group = get_object_or_404(Group, pk=pk)
    if request.method != 'POST' and not getattr(request, "_inline_group", False):
        return redirect(f"{reverse('group_list')}?edit={group.pk}")

    if request.method == 'POST':
        old_trainer = group.trainer
        old_salary_rate = group.salary_rate
        group_form = GroupForm(request.POST, instance=group)
        slot_formset = ScheduleSlotFormSet(request.POST, instance=group)

        if group_form.is_valid() and slot_formset.is_valid():
            # ModelForm уже перенёс cleaned_data в instance. Для истории
            # используем реквизиты, которые были сохранены до валидации.
            group.freeze_current_history(
                trainer=old_trainer,
                salary_rate=old_salary_rate,
            )
            group_form.save()
            slot_formset.save()
            messages.success(request, f'Группа "{group.name}" обновлена')
            return redirect('group_list')
    else:
        group_form = GroupForm(instance=group)
        slot_formset = ScheduleSlotFormSet(instance=group)

    context = {
        'group_form': group_form,
        'slot_formset': slot_formset,
        'group': group,
        'title': f'Редактирование: {group.name}',
        'page': 'groups'
    }
    context["form_title"] = context["title"]
    context["title"] = "Группы"
    context["groups"] = Group.objects.select_related("trainer").prefetch_related("schedule", "children", "subscription_tariffs").order_by("trainer__full_name", "trainer_id", "name")
    return render(request, "crm/groups.html", context)

@login_required
def group_delete_view(request, pk):
    """Удаление группы"""
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        active_children_count = group.current_children().count()
        has_history = (
            group.children.exists()
            or group.child_memberships.exists()
        )
        if has_history:
            if active_children_count:
                reason = f"с ней связано {active_children_count} действующих спортсменов"
            else:
                reason = "с ней сохранена история спортсменов"
            messages.error(
                request,
                (
                    f'Нельзя удалить группу "{group.name}": {reason}. '
                    "Переведите действующих спортсменов, затем сделайте группу неактивной — "
                    "история останется доступна."
                ),
            )
            return redirect('group_list')
        group.delete()
        messages.success(request, f'Группа "{group.name}" удалена')
        return redirect('group_list')

    context = {
        'group': group,
        'title': 'Удаление группы',
        'page': 'groups'
    }
    return render(request, 'crm/group_delete.html', context)
