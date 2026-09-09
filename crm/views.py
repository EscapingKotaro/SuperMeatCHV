from .forms import CampEventForm, CompetitionDocumentForm
from .intake_parser import parse_application
import mimetypes
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import StringIO

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from openpyxl.utils import get_column_letter
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill



from .forms import (
    ApparatusForm,
    CampStayForm,
    ChildForm,
    ChildRankForm,
    CompetitionEntryForm,
    CompetitionForm,
    ExpenseForm,
    LeadForm,
    ManagerTaskForm,
    NewcomerForm,
    ProfileForm,
    RevenueTargetForm,
    SalaryAdjustmentForm,
    StaffCreateForm,
    StyledPasswordChangeForm,
    SubscriptionForm,
    TariffForm,
)


from .models import (
    Apparatus,
    Notification,
    ApparatusScore,
    Attendance,
    AuditEvent,
    Camp,
    CampStay,
    Child,
    ChildRank,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    recalculate_competition_places,
    ManagerTask,
    Newcomer,
    Payment,
    RevenueTarget,
    Role,
    SalaryAdjustment,
    SalaryPayout,
    StaffProfile,
    Subscription,
    Tariff,
    Trainer,
    has_min_role,
    user_rank,
    user_role,
)


PAGE_META = {
    "attendance": ("Табель", "Отмечайте посещения прямо в таблице"),
    "statistics": ("Статистика", "Главные показатели клуба"),
    "payments": ("Абонементы и оплаты", ""),
    "camps": ("Лагеря и сборы", ""),
    "expenses": ("Расходы", "Бытовые закупки и другие расходы"),
    "competitions": ("Соревнования", "Баллы, места и история выступлений"),
    "notifications": ("Уведомления", "Задачи и события, требующие внимания"),
    "boss": ("Для руководителя", "Выручка, KPI и работа команды"),
    "profile": ("Мой профиль", "Личные данные и безопасность"),
    "applications": ("Заявки", "Все обращения из рекламы, сайта и звонков"),
    "newcomers": ("Новички", "Пробные занятия и переход к оплате"),
    "calendar": ("Календарь", "Напоминания и задачи команды"),
    "search": ("Поиск", "Спортсмены, заявки, группы и контакты"),
    "users": ("Пользователи", "Управление пользователями"),
}


def role_required(min_rank):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not has_min_role(request.user, min_rank):
                return HttpResponseForbidden("Недостаточно прав")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def page_context(request, page, **extra):
    title, subtitle = PAGE_META[page]
    role = user_role(request.user)
    context = {
        "page": page,
        "title": title,
        "subtitle": subtitle,
        "current_role": role,
        "is_boss": has_min_role(request.user, 2),
        "is_senior": has_min_role(request.user, 1),
    }
    context.update(extra)
    return context


def log_action(request, action, obj, description):
    event = AuditEvent.objects.create(
        actor=request.user,
        action=action,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj and obj.pk else "",
        description=description,
    )
    request._crm_audit_logged = True
    return event


def login_page(request):
    if request.user.is_authenticated:
        return redirect("attendance")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user and user.is_active:
            login(request, user)
            request.session.set_expiry(1209600 if request.POST.get("remember_me") else 0)
            return redirect(request.GET.get("next") or "attendance")
        messages.error(request, "Неверный логин или пароль")
    return render(request, "crm/login.html")


from datetime import timedelta, datetime
import calendar
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Group, ScheduleSlot, Child

from datetime import timedelta, datetime
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Group, ScheduleSlot, Child


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta, datetime
from .models import *
from .forms import ChildForm

def generate_class_dates(group, start_date, limit=60):
    """Генерирует только даты, в которые у группы есть занятия."""
    weekdays = set(ScheduleSlot.objects.filter(group=group).values_list("weekday", flat=True))
    if not weekdays:
        return []
    dates = []
    current = start_date
    while len(dates) < limit:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates


@login_required
def logout_page(request):
    log_action(
        request,
        "auth.logout",
        request.user,
        f"Выход из CRM: {request.user}",
    )
    logout(request)
    return redirect("login")

def attendance_view(request):
    group_id = request.GET.get('group_id')
    ref_date_str = request.GET.get('ref_date')
    sort_by = request.GET.get('sort', 'name')
    show_archived = request.GET.get('show_archived') == '1'

    # 1. Группа
    if group_id:
        group = get_object_or_404(Group, id=group_id)
    else:
        group = Group.objects.filter(is_active=True).first()
        if not group:
            return render(
                request,
                "crm/attendance.html",
                page_context(
                    request,
                    "attendance",
                    groups=Group.objects.none(),
                    selected_group=None,
                ),
            )

    trainer = group.trainer if group else None
    today = timezone.localdate()

    # 2. Опорная дата
    if ref_date_str:
        try:
            ref_date = datetime.strptime(ref_date_str, '%Y-%m-%d').date()
        except ValueError:
            ref_date = today
    else:
        ref_date = today

    # 3. Табель показывает только реальные дни занятий группы.
    start_of_week = ref_date - timedelta(days=35)
    all_class_dates = generate_class_dates(
        group,
        start_of_week,
        limit=60,
    )

    if not all_class_dates:
        return render(
            request,
            "crm/attendance.html",
            page_context(
                request,
                "attendance",
                groups=Group.objects.filter(is_active=True),
                selected_group=group,
                week_data=[],
                children_data=[],
                ref_date=ref_date,
                error="Нет расписания",
            ),
        )

    current_index = 0
    for i, class_date in enumerate(all_class_dates):
        if class_date >= ref_date:
            current_index = i
            break

    if all_class_dates[-1] < ref_date:
        current_index = len(all_class_dates) - 1

    start_idx = max(0, current_index - 4)
    end_idx = min(len(all_class_dates), current_index + 4)
    window_dates = all_class_dates[start_idx:end_idx]

    schedule_by_weekday = {}
    for slot in (
        ScheduleSlot.objects
        .filter(group=group)
        .order_by("weekday", "start_time")
    ):
        schedule_by_weekday.setdefault(slot.weekday, slot)

    week_data = []
    for class_date in window_dates:
        slot = schedule_by_weekday[class_date.weekday()]
        week_data.append({
            'date': class_date,
            'start_time': slot.start_time,
            'is_today': class_date == today,
            'is_future': class_date > today,
        })

    # 5. ПОЛУЧАЕМ ДЕТЕЙ (с учетом архива)
    if show_archived:
        children_qs = Child.objects.filter(
            group=group,
            status__in=[Child.Status.ARCHIVED, Child.Status.LOST]
        )
    else:
        children_qs = Child.objects.filter(
            group=group,
            status__in=[Child.Status.ACTIVE, Child.Status.TRIAL]
        )

    children_qs = children_qs.select_related('group__trainer').prefetch_related(
        'subscriptions', 'payments', 'attendances', 'ranks'
    )

    # 6. СОРТИРОВКА (превращаем в список и сортируем)
    children_list = list(children_qs)
    
    if sort_by == 'sessions':
        def completed_sessions(child):
            subscription = child.active_subscription()
            if not subscription:
                return 0
            return max(
                0,
                subscription.sessions_total - child.sessions_left(),
            )

        children_list.sort(
            key=completed_sessions,
            reverse=True,
        )
    elif sort_by == 'debt':
        children_list.sort(key=lambda c: c.debt(), reverse=True)
    else:
        children_list.sort(key=lambda c: (c.last_name.lower(), c.first_name.lower()))

    children_data = []
    for child in children_list:
        active_sub = child.active_subscription()
        sessions_left = child.sessions_left()
        projected_end = (
            child.projected_end_date()
            if active_sub and sessions_left > 0
            else None
        )

        # Единая граница для табеля: абонемент заканчивается либо по
        # исчерпанию занятий, либо по календарной дате — что наступит раньше.
        subscription_end = None
        if active_sub:
            end_candidates = [active_sub.end_date]
            if sessions_left <= 0:
                end_candidates.append(today)
            elif projected_end:
                end_candidates.append(projected_end)
            subscription_end = min(end_candidates)

        att_map = {}
        for att in child.attendances.filter(date__in=window_dates):
            att_map[att.date] = att.status

        entries = []
        sub_end_index = None
        subscription_end_before_window = False
        subscription_ending_soon = (
            subscription_end is not None
            and 0 <= (subscription_end - today).days <= 7
        )

        for idx, wd in enumerate(week_data):
            status = att_map.get(wd['date'], '')
            entries.append({
                'date': wd['date'],
                'status': status,
                'is_future': wd['is_future'],
            })

        # Календарная дата окончания может приходиться на день без занятия.
        # Тогда границу ставим после последнего видимого занятия до неё.
        # Если окончание уже перед первым видимым занятием — рисуем границу
        # слева от первой колонки.
        if subscription_end and week_data:
            if subscription_end < week_data[0]['date']:
                subscription_end_before_window = True
            elif subscription_end <= week_data[-1]['date']:
                for idx, wd in enumerate(week_data):
                    if wd['date'] <= subscription_end:
                        sub_end_index = idx
                    else:
                        break

        children_data.append({
            'child': child,
            'initials': f"{child.last_name[0]}{child.first_name[0]}".upper(),
            'age': child.age_display(),
            'sessions_left': sessions_left,
            'sessions_total': active_sub.sessions_total if active_sub else 0,
            'subscription_id': active_sub.pk if active_sub else None,
            'debt': child.debt(),
            'has_certificate': child.has_certificate(),
            'discount_percent': child.discount_percent,
            'subscription_end': subscription_end,
            'subscription_end_index': sub_end_index,
            'subscription_end_before_window': subscription_end_before_window,
            'subscription_ending_soon': subscription_ending_soon,
            'is_trial': child.status == Child.Status.TRIAL,
            'is_archived': child.status in [Child.Status.ARCHIVED, Child.Status.LOST],
            'attendance_entries': entries,
        })

    # Плавный сдвиг на одно занятие без пропусков между окнами.
    prev_ref = all_class_dates[current_index - 1].isoformat()
    next_ref = all_class_dates[current_index + 1].isoformat()

    # Базовые параметры для ссылок, чтобы сортировка не слетала
    base_params = f"group_id={group.id}&ref_date={{}}&sort={sort_by}"
    if show_archived:
        base_params += "&show_archived=1"

    context = page_context(
        request,
        "attendance",
        groups=Group.objects.filter(is_active=True),
        selected_group=group,
        trainer=trainer,
        week_data=week_data,
        children_data=children_data,
        ref_date=ref_date,
        prev_ref=prev_ref,
        next_ref=next_ref,
        today=today,
        sort_by=sort_by,
        show_archived=show_archived,
        base_params=base_params,
    )

    return render(request, "crm/attendance.html", context)


@login_required
@require_POST
def archive_child_view(request, child_id):
    """Перевод ребенка в архив"""
    child = get_object_or_404(Child, id=child_id)
    child.archive()
    messages.success(request, f'{child.last_name} {child.first_name} архивирован')
    return redirect('attendance')


@login_required
@require_POST
def restore_child_view(request, child_id):
    """Восстановление из архива"""
    child = get_object_or_404(Child, id=child_id)
    child.restore_from_archive()
    messages.success(request, f'{child.last_name} {child.first_name} восстановлен')
    return redirect('attendance')


@login_required
@require_POST
def add_trial_child_view(request, group_id):
    """Добавление ребенка на пробное занятие"""
    group = get_object_or_404(Group, id=group_id)
    
    if request.method == 'POST':
        last_name = request.POST.get('last_name')
        first_name = request.POST.get('first_name')
        parent_phone = request.POST.get('parent_phone')
        
        if last_name and first_name:
            child = Child.objects.create(
                last_name=last_name,
                first_name=first_name,
                parent_phone=parent_phone,
                group=group,
                status=Child.Status.TRIAL,
                trial_from=timezone.localdate()
            )
            messages.success(request, f'{child.last_name} {child.first_name} добавлен на пробное (14 дней)')
            return redirect('attendance')
    
    return redirect('attendance')


@login_required
@require_POST
def cancel_attendance_view(request):
    """Отмена отметки через правый клик"""
    child_id = request.POST.get('child_id')
    date_str = request.POST.get('date')
    
    if child_id and date_str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            attendance = Attendance.objects.filter(child_id=child_id, date=date).first()
            if attendance:
                attendance.delete()
                return JsonResponse({'status': 'ok', 'message': 'Отметка отменена'})
        except ValueError:
            pass
    
    return JsonResponse({'status': 'error', 'message': 'Ошибка'}, status=400)

@login_required
@require_POST
def mark_attendance_view(request):
    """Поставить или изменить отметку посещения."""

    child_id = request.POST.get("child_id")
    date_str = request.POST.get("date")
    status = request.POST.get("status")

    if not child_id or not date_str or not status:
        return JsonResponse(
            {
                "status": "error",
                "message": "Не передан child_id, date или status",
            },
            status=400,
        )

    try:
        mark_date = date.fromisoformat(date_str)
    except ValueError:
        return JsonResponse(
            {
                "status": "error",
                "message": "Некорректная дата",
            },
            status=400,
        )

    if mark_date > timezone.localdate():
        return JsonResponse(
            {
                "status": "error",
                "message": "Нельзя ставить отметки за будущие занятия",
            },
            status=400,
        )

    child = get_object_or_404(Child, pk=child_id)

    allowed_statuses = {
        Attendance.Status.PRESENT,
        Attendance.Status.ABSENT,
        Attendance.Status.EXCUSED,
        Attendance.Status.FROZEN,
        Attendance.Status.VACATION,
    }

    if status not in allowed_statuses:
        return JsonResponse(
            {
                "status": "error",
                "message": "Некорректный статус",
            },
            status=400,
        )

    charge = Decimal("0")

    if (
        status == Attendance.Status.PRESENT
        and not child.active_subscription()
        and child.group
    ):
        charge = child.group.single_session_price

    attendance = Attendance.objects.filter(
        child=child,
        date=mark_date,
        slot=None,
    ).first()

    if attendance is None:
        created = True
        attendance = Attendance.objects.create(
            child=child,
            date=mark_date,
            slot=None,
            group_snapshot=child.group,
            trainer_snapshot=child.trainer,
            salary_rate_snapshot=(
                child.group.salary_rate
                if child.group
                else None
            ),
            status=status,
            charge_amount=charge,
        )
    else:
        created = False
        update_fields = ["status", "charge_amount"]
        attendance.status = status
        attendance.charge_amount = charge

        if attendance.group_snapshot_id is None and child.group:
            attendance.group_snapshot = child.group
            attendance.trainer_snapshot = child.trainer
            attendance.salary_rate_snapshot = child.group.salary_rate
            update_fields.extend([
                "group_snapshot",
                "trainer_snapshot",
                "salary_rate_snapshot",
            ])

        attendance.save(update_fields=update_fields)

    return JsonResponse(
        {
            "status": "ok",
            "created": created,
            "attendance_id": attendance.pk,
        }
    )

@login_required
@transaction.atomic
def payments_page(request):
    editing_tariff = Tariff.objects.filter(pk=request.GET.get("edit_tariff")).first()
    editing_subscription = Subscription.objects.filter(pk=request.GET.get("edit_subscription")).first()
    tariff_form = TariffForm(request.POST or None, prefix="tariff", instance=editing_tariff)
    subscription_form = SubscriptionForm(
        request.POST or None, prefix="subscription", instance=editing_subscription,
        initial={"start_date": timezone.localdate(), "child": request.GET.get("child")} if editing_subscription is None else None,
    )
    if request.method == "POST":
        action = request.POST.get("action", "payment")
        if action == "payment":
            child = get_object_or_404(Child, pk=request.POST.get("child_id"))
            from django import forms as django_forms
            try:
                amount = django_forms.DecimalField(min_value=Decimal("0.01"), max_digits=10, decimal_places=2).clean(request.POST.get("amount"))
                payment_date = django_forms.DateField().clean(request.POST.get("date") or timezone.localdate())
            except django_forms.ValidationError:
                messages.error(request, "Укажите корректную дату и положительную сумму оплаты")
            else:
                payment = Payment.objects.create(
                    child=child,
                    subscription=child.active_subscription(),
                    amount=amount,
                    date=payment_date,
                    created_by=request.user,
                )
                log_action(request, "payment.create", payment, f"Принята оплата {amount} ₽ от {child}")
                messages.success(request, "Оплата сохранена")
        elif action == "save_tariff":
            tariff_form = TariffForm(request.POST, prefix="tariff", instance=editing_tariff)
            if tariff_form.is_valid():
                tariff = tariff_form.save()
                log_action(request, "tariff.save", tariff, f"Сохранён тариф {tariff.name}")
                messages.success(request, "Тариф сохранён")
            else:
                messages.error(request, "Проверьте параметры тарифа")
                return render(request, "crm/payments.html", page_context(
                    request, "payments", tariff_form=tariff_form,
                    subscription_form=SubscriptionForm(prefix="subscription"), tariffs=Tariff.objects.all(),
                    subscriptions=Subscription.objects.select_related("child", "tariff"),
                    children=Child.objects.filter(
                        status__in=[Child.Status.ACTIVE, Child.Status.TRIAL],
                    ),
                    renewals=[], urgent_count=0, expected=0, editing_tariff=editing_tariff,
                ))
        elif action == "toggle_tariff":
            tariff = get_object_or_404(Tariff, pk=request.POST.get("tariff_id"))
            tariff.is_active = not tariff.is_active
            tariff.save(update_fields=["is_active"])
            messages.success(request, "Статус тарифа изменён")
        elif action == "save_subscription":
            subscription_form = SubscriptionForm(request.POST, prefix="subscription", instance=editing_subscription)
            if subscription_form.is_valid():
                subscription = subscription_form.save()
                if subscription.is_active:
                    Subscription.objects.filter(
                        child=subscription.child, is_active=True,
                        start_date__lte=subscription.end_date, end_date__gte=subscription.start_date,
                    ).exclude(pk=subscription.pk).update(is_active=False)
                log_action(request, "subscription.save", subscription, f"Сохранён абонемент {subscription}")
                messages.success(request, "Абонемент назначен")
            else:
                messages.error(request, "Проверьте данные абонемента")
        elif action == "cancel_subscription":
            subscription = get_object_or_404(Subscription, pk=request.POST.get("subscription_id"))
            subscription.cancel()
            log_action(request, "subscription.cancel", subscription, f"Отменён абонемент {subscription}")
            messages.success(request, "Абонемент отменён без удаления истории")
        if action != "save_subscription" or not subscription_form.errors:
            return redirect("payments")

    month_start, month_end, today = _month_range(request)
    rows = build_renewal_rows(
        month_start,
        month_end,
        today,
    )
    expected = sum(
        (row["amount"] for row in rows),
        Decimal("0"),
    )

    return render(request, "crm/payments.html", page_context(
        request,
        "payments",
        renewals=rows,
        rows=rows,
        month_start=month_start,
        month_end=month_end,
        children=Child.objects.filter(
            status__in=[Child.Status.ACTIVE, Child.Status.TRIAL],
        ),
        urgent_count=sum(
            1 for row in rows
            if row["status"] == "Срочно"
        ),
        expected=expected,
        tariff_preview=list(Tariff.objects.values("id", "price", "sessions_total", "duration_days")),
        child_discounts=list(Child.objects.values("id", "discount_percent")),
        tariffs=Tariff.objects.all(),
        subscriptions=Subscription.objects.select_related("child", "tariff")[:100],
        tariff_form=tariff_form,
        subscription_form=subscription_form,
        editing_tariff=editing_tariff,
        editing_subscription=editing_subscription,
    ))


@login_required
def expenses_page(request):
    today = timezone.localdate()
    month_raw = request.GET.get("month", "").strip()

    try:
        month_start = (
            datetime.strptime(month_raw, "%Y-%m").date().replace(day=1)
            if month_raw
            else today.replace(day=1)
        )
    except ValueError:
        month_start = today.replace(day=1)

    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = (
            date(month_start.year, month_start.month + 1, 1)
            - timedelta(days=1)
        )

    selected_category = request.GET.get("category", "").strip()
    valid_categories = {
        value for value, _ in Expense.Category.choices
    }

    if selected_category not in valid_categories:
        selected_category = ""

    filter_url = (
        f"{reverse('expenses')}?month={month_start:%Y-%m}"
    )

    if selected_category:
        filter_url += f"&category={selected_category}"

    can_manage_all = has_min_role(request.user, 1)

    editing = (
        Expense.objects
        .filter(pk=request.GET.get("edit"))
        .select_related("created_by")
        .first()
    )

    if editing and not (
        can_manage_all
        or editing.created_by_id == request.user.id
    ):
        return HttpResponseForbidden(
            "Недостаточно прав для редактирования этого расхода"
        )

    form = ExpenseForm(
        request.POST or None,
        request.FILES or None,
        instance=editing,
    )

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "delete":
            expense = get_object_or_404(
                Expense,
                pk=request.POST.get("expense_id"),
            )

            if not can_manage_all:
                return HttpResponseForbidden(
                    "Удалять расходы может только старший администратор "
                    "или начальник"
                )

            log_action(
                request,
                "expense.delete",
                expense,
                f"Удалён расход {expense.title} на {expense.amount} ₽",
            )

            expense.delete()
            messages.success(request, "Расход удалён")

            return redirect(filter_url)

        if form.is_valid():
            expense = form.save(commit=False)

            if expense.pk:
                if not (
                    can_manage_all
                    or expense.created_by_id == request.user.id
                ):
                    return HttpResponseForbidden(
                        "Недостаточно прав для редактирования этого расхода"
                    )
            else:
                expense.created_by = request.user

            expense.save()

            log_action(
                request,
                "expense.save",
                expense,
                f"Сохранён расход {expense.title} на {expense.amount} ₽",
            )

            messages.success(request, "Расход сохранён")
            return redirect(filter_url)

        messages.error(
            request,
            "Проверьте заполнение формы",
        )

    monthly_expenses = (
        Expense.objects
        .select_related("created_by")
        .filter(
            date__gte=month_start,
            date__lte=month_end,
        )
        .order_by("-date", "-pk")
    )

    expenses = monthly_expenses

    if selected_category:
        expenses = expenses.filter(
            category=selected_category,
        )

    total = (
        expenses.aggregate(
            value=Sum("amount"),
        )["value"]
        or Decimal("0")
    )

    monthly_total = (
        monthly_expenses.aggregate(
            value=Sum("amount"),
        )["value"]
        or Decimal("0")
    )

    category_labels = dict(
        Expense.Category.choices
    )

    category_rows = [
        {
            "category": row["category"],
            "label": category_labels.get(
                row["category"],
                row["category"],
            ),
            "total": row["total"],
            "operations": row["operations"],
        }
        for row in (
            monthly_expenses
            .values("category")
            .annotate(
                total=Sum("amount"),
                operations=Count("id"),
            )
            .order_by("-total", "category")
        )
    ]

    return render(
        request,
        "crm/expenses.html",
        page_context(
            request,
            "expenses",
            form=form,
            expenses=expenses,
            editing=editing,
            total=total,
            monthly_total=monthly_total,
            operations=expenses.count(),
            monthly_operations=monthly_expenses.count(),
            category_rows=category_rows,
            month_start=month_start,
            month_end=month_end,
            selected_month=month_start.strftime("%Y-%m"),
            selected_category=selected_category,
            categories=Expense.Category.choices,
            can_manage_all=can_manage_all,
            filter_url=filter_url,
        ),
    )


def _normalize_import_text(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("ё", "е").split())


def _excel_value(row, column):
    if not column or column > len(row):
        return None
    return row[column - 1]


def _import_external_competition_results(competition, uploaded_file):
    """Импорт выездного протокола XLSX.

    Поддерживает формат экспорта самой CRM:
    Спортсмен, Год рождения, Разряд, Категория, дисциплины..., Итого, Место.
    Также понимает ФИО вместо Спортсмен и Год вместо Год рождения.
    """
    workbook = load_workbook(uploaded_file, data_only=True)
    worksheet = workbook.active

    first_row = next(
        worksheet.iter_rows(min_row=1, max_row=1, values_only=True),
        None,
    )
    if not first_row:
        raise ValueError("Excel-файл пуст")

    headers = {
        _normalize_import_text(value): index
        for index, value in enumerate(first_row, start=1)
        if _normalize_import_text(value)
    }

    athlete_col = headers.get("спортсмен") or headers.get("фио")
    year_col = headers.get("год рождения") or headers.get("год")
    rank_col = headers.get("разряд")
    category_col = headers.get("категория") or headers.get("категория/группа")
    place_col = headers.get("место")

    if not athlete_col or not place_col:
        raise ValueError(
            "В таблице обязательны столбцы «Спортсмен» (или «ФИО») и «Место»"
        )

    apparatus = list(competition.apparatus.all())
    apparatus_columns = {
        item.pk: headers.get(_normalize_import_text(item.name))
        for item in apparatus
    }

    children_by_name = defaultdict(list)
    for child in Child.objects.all():
        aliases = {
            _normalize_import_text(str(child)),
            _normalize_import_text(
                f"{child.last_name} {child.first_name} {child.patronymic}"
            ),
        }
        for alias in aliases:
            if alias:
                children_by_name[alias].append(child)

    imported = 0
    skipped = []

    for row_number, row in enumerate(
        worksheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        if not any(value not in (None, "") for value in row):
            continue

        raw_name = _excel_value(row, athlete_col)
        normalized_name = _normalize_import_text(raw_name)
        if not normalized_name:
            skipped.append(f"Строка {row_number}: не указано ФИО")
            continue

        candidates = list(children_by_name.get(normalized_name, []))

        raw_year = _excel_value(row, year_col)
        birth_year = None
        if raw_year not in (None, ""):
            try:
                birth_year = int(float(raw_year))
            except (TypeError, ValueError):
                skipped.append(
                    f"Строка {row_number}: некорректный год рождения"
                )
                continue

        if birth_year is not None:
            candidates = [
                child for child in candidates
                if child.birth_year == birth_year
            ]

        if len(candidates) != 1:
            skipped.append(
                f"Строка {row_number}: не удалось однозначно найти «{raw_name}»"
            )
            continue

        raw_place = _excel_value(row, place_col)
        try:
            place = int(float(raw_place))
            if place <= 0:
                raise ValueError
        except (TypeError, ValueError):
            skipped.append(
                f"Строка {row_number}: место должно быть положительным числом"
            )
            continue

        child = candidates[0]
        category = str(_excel_value(row, category_col) or "").strip()
        rank = str(_excel_value(row, rank_col) or "").strip()

        entry, _ = CompetitionEntry.objects.update_or_create(
            child=child,
            competition=competition,
            category=category,
            defaults={
                "rank": rank,
                "place": place,
            },
        )

        for item in apparatus:
            column = apparatus_columns.get(item.pk)
            if not column:
                continue

            raw_points = _excel_value(row, column)
            if raw_points in (None, ""):
                continue

            try:
                points = Decimal(str(raw_points).replace(",", "."))
            except InvalidOperation:
                skipped.append(
                    f"Строка {row_number}: неверный балл «{item.name}»"
                )
                continue

            if not points.is_finite() or points < 0:
                skipped.append(
                    f"Строка {row_number}: неверный балл «{item.name}»"
                )
                continue

            ApparatusScore.objects.update_or_create(
                entry=entry,
                apparatus=item,
                defaults={"points": points},
            )

        imported += 1

    return imported, skipped


@login_required
def competitions_page(request):
    competitions = Competition.objects.all()

    selected = (
        competitions.filter(
            pk=request.GET.get("competition"),
        ).first()
        or competitions.first()
    )

    editing_competition = competitions.filter(
        pk=request.GET.get("edit_competition"),
    ).first()

    editing_apparatus = None
    editing_entry = None

    if selected:
        editing_apparatus = selected.apparatus.filter(
            pk=request.GET.get("edit_apparatus"),
        ).first()

        editing_entry = selected.entries.filter(
            pk=request.GET.get("edit_entry"),
        ).first()

    competition_form = CompetitionForm(
        prefix="competition",
        instance=editing_competition,
    )

    apparatus_form = ApparatusForm(
        prefix="apparatus",
        instance=editing_apparatus,
    )

    entry_form = CompetitionEntryForm(
        prefix="entry",
        instance=editing_entry,
        competition=selected,
    )

    document_form = CompetitionDocumentForm(competition=selected)
    if request.method == "POST" and request.POST.get("action") == "upload_document":
        selected = get_object_or_404(Competition, pk=request.POST.get("competition_id"))
        document_form = CompetitionDocumentForm(request.POST, request.FILES, competition=selected)
        if document_form.is_valid():
            document = document_form.save(commit=False)
            document.competition = selected
            document.save()
            log_action(request, "competition.document", document, f"Добавлен документ: {document.title}")
            return redirect(f"{reverse('competitions')}?competition={selected.pk}#documents")
        messages.error(request, "Проверьте документ")

    score_draft = {}

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_competition":
            competition_id = request.POST.get(
                "competition_id"
            )

            target = (
                competitions.filter(
                    pk=competition_id,
                ).first()
                if competition_id
                else None
            )

            competition_form = CompetitionForm(
                request.POST,
                prefix="competition",
                instance=target,
            )

            if competition_form.is_valid():
                selected = competition_form.save()

                if target is None:
                    default_apparatus = (
                        "Прыжок",
                        "Брусья",
                        "Бревно",
                        "Вольные",
                    )

                    for order, name in enumerate(
                        default_apparatus
                    ):
                        Apparatus.objects.create(
                            competition=selected,
                            name=name,
                            order=order,
                        )

                log_action(
                    request,
                    "competition.save",
                    selected,
                    f"Сохранено соревнование {selected.name}",
                )

                messages.success(
                    request,
                    "Соревнование сохранено",
                )

                return redirect(
                    f"{reverse('competitions')}"
                    f"?competition={selected.pk}"
                )

            messages.error(
                request,
                "Проверьте данные соревнования",
            )

        elif action == "delete_competition":
            competition = get_object_or_404(
                Competition,
                pk=request.POST.get("competition_id"),
            )

            name = competition.name

            log_action(
                request,
                "competition.delete",
                competition,
                f"Удалено соревнование {name}",
            )

            competition.delete()

            messages.success(
                request,
                f"Соревнование «{name}» удалено",
            )

            return redirect("competitions")

        elif action == "save_apparatus" and selected:
            apparatus_id = request.POST.get(
                "apparatus_id"
            )

            target = (
                selected.apparatus.filter(
                    pk=apparatus_id,
                ).first()
                if apparatus_id
                else None
            )

            apparatus_form = ApparatusForm(
                request.POST,
                prefix="apparatus",
                instance=target,
            )

            if apparatus_form.is_valid():
                is_new = target is None

                apparatus_item = apparatus_form.save(
                    commit=False
                )

                apparatus_item.competition = selected

                if is_new:
                    max_order = (
                        selected.apparatus.aggregate(
                            value=Max("order")
                        )["value"]
                    )

                    apparatus_item.order = (
                        max_order + 1
                        if max_order is not None
                        else 0
                    )

                apparatus_item.save()

                if is_new:
                    for entry in selected.entries.all():
                        ApparatusScore.objects.get_or_create(
                            entry=entry,
                            apparatus=apparatus_item,
                            defaults={
                                "points": None,
                            },
                        )

                    if selected.is_internal:
                        recalculate_competition_places(selected)

                log_action(
                    request,
                    "competition.apparatus",
                    apparatus_item,
                    (
                        "Сохранена дисциплина "
                        f"{apparatus_item.name}"
                    ),
                )

                messages.success(
                    request,
                    "Дисциплина сохранена",
                )

                return redirect(
                    f"{reverse('competitions')}"
                    f"?competition={selected.pk}"
                )

            messages.error(
                request,
                "Проверьте название дисциплины",
            )

        elif action == "delete_apparatus" and selected:
            apparatus_item = get_object_or_404(
                selected.apparatus,
                pk=request.POST.get("apparatus_id"),
            )

            name = apparatus_item.name

            apparatus_item.delete()

            if selected.is_internal:
                recalculate_competition_places(selected)

            log_action(
                request,
                "competition.apparatus.delete",
                selected,
                f"Удалена дисциплина {name}",
            )

            messages.success(
                request,
                "Дисциплина и её баллы удалены",
            )

            return redirect(
                f"{reverse('competitions')}"
                f"?competition={selected.pk}"
            )

        elif action == "save_entry" and selected:
            entry_id = request.POST.get("entry_id")

            target = (
                get_object_or_404(
                    selected.entries,
                    pk=entry_id,
                )
                if entry_id
                else None
            )

            entry_form = CompetitionEntryForm(
                request.POST,
                prefix="entry",
                instance=target,
                competition=selected,
            )

            if entry_form.is_valid():
                previous_child_id = (
                    target.child_id
                    if target
                    else None
                )

                entry = entry_form.save(
                    commit=False
                )

                entry.competition = selected

                # Если администратор исправил самого участника в существующей
                # записи, снимок группы должен соответствовать новому ребёнку.
                if (
                    target
                    and entry.child_id != previous_child_id
                ):
                    entry.group_snapshot_id = entry.child.group_id

                entry.save()

                for apparatus_item in selected.apparatus.all():
                    ApparatusScore.objects.get_or_create(
                        entry=entry,
                        apparatus=apparatus_item,
                        defaults={
                            "points": None,
                        },
                    )

                if selected.is_internal:
                    recalculate_competition_places(selected)

                log_action(
                    request,
                    "competition.entry",
                    entry,
                    (
                        f"Сохранён участник "
                        f"{entry.child} в {selected.name}"
                    ),
                )

                messages.success(
                    request,
                    "Участник сохранён",
                )

                return redirect(
                    f"{reverse('competitions')}"
                    f"?competition={selected.pk}"
                )

            messages.error(
                request,
                "Проверьте данные участника",
            )

        elif action == "delete_entry" and selected:
            entry = get_object_or_404(
                selected.entries,
                pk=request.POST.get("entry_id"),
            )

            child_name = str(entry.child)

            log_action(
                request,
                "competition.entry.delete",
                entry,
                (
                    f"Удалён участник {child_name} "
                    f"из {selected.name}"
                ),
            )

            entry.delete()

            if selected.is_internal:
                recalculate_competition_places(selected)

            messages.success(
                request,
                "Участник удалён",
            )

            return redirect(
                f"{reverse('competitions')}"
                f"?competition={selected.pk}"
            )

        elif action == "import_results" and selected:
            if selected.is_internal:
                messages.error(
                    request,
                    "Импорт ручного протокола доступен только для выездных соревнований",
                )
            else:
                results_file = request.FILES.get("results_file")

                if not results_file:
                    messages.error(request, "Выберите XLSX-файл с результатами")
                elif not results_file.name.lower().endswith(".xlsx"):
                    messages.error(request, "Поддерживаются только файлы .xlsx")
                else:
                    try:
                        with transaction.atomic():
                            imported, skipped = _import_external_competition_results(
                                selected,
                                results_file,
                            )
                    except (ValueError, OSError) as exc:
                        messages.error(request, f"Не удалось импортировать таблицу: {exc}")
                    else:
                        messages.success(
                            request,
                            f"Импортировано строк: {imported}",
                        )
                        for warning in skipped[:5]:
                            messages.warning(request, warning)
                        if len(skipped) > 5:
                            messages.warning(
                                request,
                                f"И ещё пропущено строк: {len(skipped) - 5}",
                            )

                        log_action(
                            request,
                            "competition.import",
                            selected,
                            (
                                f"Импортирован выездной протокол "
                                f"{selected.name}: {imported} строк"
                            ),
                        )

            return redirect(
                f"{reverse('competitions')}"
                f"?competition={selected.pk}"
            )

        elif action == "save_scores" and selected:
            entries = list(
                selected.entries.all()
            )

            apparatus_items = list(
                selected.apparatus.all()
            )

            parsed_scores = []
            errors = []

            for entry in entries:
                for apparatus_item in apparatus_items:
                    key = (
                        f"score_{entry.pk}_"
                        f"{apparatus_item.pk}"
                    )

                    raw = request.POST.get(
                        key,
                        "",
                    ).strip()

                    score_draft[key] = raw

                    if raw == "":
                        parsed_scores.append(
                            (
                                entry,
                                apparatus_item,
                                None,
                            )
                        )
                        continue

                    normalized = raw.replace(
                        ",",
                        ".",
                    )

                    try:
                        points = Decimal(normalized)
                    except InvalidOperation:
                        errors.append(
                            (
                                f"{entry.child}: "
                                f"«{apparatus_item.name}» — "
                                "некорректный балл"
                            )
                        )
                        continue

                    if not points.is_finite():
                        errors.append(
                            (
                                f"{entry.child}: "
                                f"«{apparatus_item.name}» — "
                                "некорректный балл"
                            )
                        )
                        continue

                    if points < 0:
                        errors.append(
                            (
                                f"{entry.child}: "
                                f"«{apparatus_item.name}» — "
                                "балл не может быть отрицательным"
                            )
                        )
                        continue

                    normalized_points = points.normalize()

                    decimal_places = max(
                        -normalized_points.as_tuple().exponent,
                        0,
                    )

                    if decimal_places > 3:
                        errors.append(
                            (
                                f"{entry.child}: "
                                f"«{apparatus_item.name}» — "
                                "не более 3 знаков после запятой"
                            )
                        )
                        continue

                    parsed_scores.append(
                        (
                            entry,
                            apparatus_item,
                            points,
                        )
                    )

            if errors:
                for error in errors[:5]:
                    messages.error(
                        request,
                        error,
                    )

                if len(errors) > 5:
                    messages.error(
                        request,
                        (
                            f"И ещё ошибок: "
                            f"{len(errors) - 5}"
                        ),
                    )

            else:
                with transaction.atomic():
                    for (
                        entry,
                        apparatus_item,
                        points,
                    ) in parsed_scores:
                        ApparatusScore.objects.update_or_create(
                            entry=entry,
                            apparatus=apparatus_item,
                            defaults={
                                "points": points,
                            },
                        )

                    if selected.is_internal:
                        recalculate_competition_places(selected)

                log_action(
                    request,
                    "competition.scores",
                    selected,
                    (
                        f"Обновлены результаты "
                        f"{selected.name}"
                    ),
                )

                messages.success(
                    request,
                    (
                        "Баллы сохранены, места пересчитаны"
                        if selected.is_internal
                        else "Баллы сохранены. Места выездного соревнования оставлены ручными"
                    ),
                )

                return redirect(
                    f"{reverse('competitions')}"
                    f"?competition={selected.pk}"
                )

    apparatus = (
        list(selected.apparatus.all())
        if selected
        else []
    )

    entry_rows = []

    if selected:
        entries = (
            selected.entries
            .select_related("child", "competition")
            .prefetch_related("scores")
        )

        for entry in entries:
            score_map = {
                score.apparatus_id: score
                for score in entry.scores.all()
            }

            score_cells = []

            for apparatus_item in apparatus:
                key = (
                    f"score_{entry.pk}_"
                    f"{apparatus_item.pk}"
                )

                if key in score_draft:
                    value = score_draft[key]
                else:
                    score = score_map.get(
                        apparatus_item.pk
                    )

                    if (
                        score is None
                        or score.points is None
                    ):
                        value = ""
                    else:
                        value = f"{score.points:.3f}"

                score_cells.append({
                    "apparatus_id": apparatus_item.pk,
                    "value": value,
                })

            total = entry.total_points()

            entry_rows.append({
                "entry": entry,
                "scores": score_cells,
                "total": total,
                "complete": total is not None,
            })

    return render(
        request,
        "crm/competitions.html",
        page_context(
            request,
            "competitions",
            competitions=competitions,
            selected=selected,
            document_form=document_form,
            documents=selected.documents.select_related("child") if selected else [],
            apparatus=apparatus,
            entry_rows=entry_rows,
            competition_form=competition_form,
            entry_form=entry_form,
            apparatus_form=apparatus_form,
            editing_competition=editing_competition,
            editing_apparatus=editing_apparatus,
            editing_entry=editing_entry,
            table_colspan=7 + len(apparatus),
        ),
    )


@login_required
def competition_export(request, pk):
    competition = get_object_or_404(
        Competition,
        pk=pk,
    )

    apparatus = list(
        competition.apparatus.all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Результаты"

    headers = [
        "Спортсмен",
        "Год рождения",
        "Разряд",
        "Категория",
        *[item.name for item in apparatus],
        "Итого",
        "Место",
    ]

    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(
            bold=True,
            color="FFFFFF",
        )
        cell.fill = PatternFill(
            "solid",
            fgColor="17202A",
        )
        cell.alignment = Alignment(
            horizontal="center",
        )

    entries = (
        competition.entries
        .select_related("child", "competition")
        .prefetch_related("scores")
    )

    for entry in entries:
        score_map = {
            score.apparatus_id: score.points
            for score in entry.scores.all()
        }

        total = entry.total_points()

        score_values = []

        for apparatus_item in apparatus:
            points = score_map.get(
                apparatus_item.pk
            )

            score_values.append(
                float(points)
                if points is not None
                else ""
            )

        ws.append([
            str(entry.child),
            entry.child.birth_year,
            entry.rank,
            entry.category,
            *score_values,
            (
                float(total)
                if total is not None
                else ""
            ),
            entry.place or "",
        ])

    widths = [
        28,
        14,
        14,
        18,
        *([12] * len(apparatus)),
        12,
        10,
    ]

    for index, width in enumerate(
        widths,
        start=1,
    ):
        ws.column_dimensions[
            get_column_letter(index)
        ].width = width

    response = HttpResponse(
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

    response["Content-Disposition"] = (
        f'attachment; filename="competition-{competition.pk}.xlsx"'
    )

    wb.save(response)

    log_action(
        request,
        "competition.export",
        competition,
        f"Выгружены результаты {competition.name}",
    )

    return response


def task_recipient_ids(task):
    if task.assignee_id:
        return {task.assignee_id}

    return set(
        get_user_model().objects
        .filter(is_active=True, is_staff=True)
        .values_list("id", flat=True)
    )


def boss_ids():
    return set(
        get_user_model().objects
        .filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(profile__role__in=(Role.BOSS, Role.ADMIN))
        )
        .values_list("id", flat=True)
    )

def notify_admins(actor, kind, message, url=""):
    recipients = (
        get_user_model().objects
        .filter(is_active=True, is_staff=True)
        .exclude(pk=actor.pk)
        .values_list("id", flat=True)
    )

    Notification.objects.bulk_create([
        Notification(
            recipient_id=user_id,
            actor=actor,
            kind=kind,
            message=message,
            url=url,
        )
        for user_id in recipients
    ])


def notify_task(task, actor, kind):
    recipients = task_recipient_ids(task)

    if kind == Notification.Kind.TASK_COMPLETED:
        recipients = boss_ids()
        if task.created_by_id:
            recipients.add(task.created_by_id)

    elif kind == Notification.Kind.TASK_REOPENED:
        recipients |= boss_ids()
        if task.created_by_id:
            recipients.add(task.created_by_id)

    recipients.discard(actor.pk)

    if not recipients:
        return

    name = actor.get_full_name() or actor.username
    texts = {
        Notification.Kind.TASK_CREATED: f"Новая задача «{task.title}»",
        Notification.Kind.TASK_UPDATED: f"{name} изменил задачу «{task.title}»",
        Notification.Kind.TASK_COMPLETED: f"{name} выполнил задачу «{task.title}»",
        Notification.Kind.TASK_REOPENED: f"{name} вернул задачу «{task.title}» в работу",
        Notification.Kind.TASK_DELETED: f"{name} удалил задачу «{task.title}»",
    }

    Notification.objects.bulk_create([
        Notification(
            recipient_id=user_id,
            actor=actor,
            task=task,
            kind=kind,
            message=texts[kind],
        )
        for user_id in recipients
    ])

def can_complete_manager_task(user, task):
    return (
        task.assignee_id is None
        or task.assignee_id == user.pk
        or has_min_role(user, 2)
    )


def can_manage_manager_task(user, task):
    return (
        task.created_by_id == user.pk
        or has_min_role(user, 2)
    )


def toggle_manager_task(task, user, completion_comment=""):
    if task.is_done:
        task.is_done = False
        task.done_at = task.completed_by = None
        task.completion_comment = ""
        kind = Notification.Kind.TASK_REOPENED
    else:
        task.is_done = True
        task.done_at = timezone.now()
        task.completed_by = user
        task.completion_comment = completion_comment.strip()
        kind = Notification.Kind.TASK_COMPLETED

    task.save(update_fields=["is_done", "done_at", "completed_by", "completion_comment"])
    notify_task(task, user, kind)

@login_required
def notifications_page(request):
    if request.method == "POST":
        action = request.POST.get("action", "toggle_task")
        if action == "mark_read":
            Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
            return redirect("notifications")

        if action == "confirm_trial":
            newcomer = get_object_or_404(
                Newcomer,
                pk=request.POST.get("newcomer_id"),
            )

            if not newcomer.trial_at:
                messages.error(
                    request,
                    "У пробного занятия не указана дата",
                )
                return redirect("notifications")

            trial_date = timezone.localtime(
                newcomer.trial_at
            ).date()

            if trial_date != timezone.localdate():
                messages.error(
                    request,
                    "Подтверждать можно пробное занятие на сегодня",
                )
                return redirect("notifications")

            newcomer.attended = True
            newcomer.lesson_cancelled = False

            newcomer.save(
                update_fields=[
                    "attended",
                    "lesson_cancelled",
                ]
            )

            log_action(
                request,
                "newcomer.trial_attended",
                newcomer,
                (
                    f"Подтверждён приход на пробное: "
                    f"{newcomer.full_name}"
                ),
            )

            messages.success(
                request,
                f"{newcomer.full_name}: приход подтверждён",
            )

            return redirect("notifications")

        if action == "cancel_trial":
            newcomer = get_object_or_404(
                Newcomer,
                pk=request.POST.get("newcomer_id"),
            )

            newcomer.attended = False
            newcomer.lesson_cancelled = True

            newcomer.save(
                update_fields=[
                    "attended",
                    "lesson_cancelled",
                ]
            )

            log_action(
                request,
                "newcomer.trial_cancelled",
                newcomer,
                (
                    f"Пробное занятие отменено: "
                    f"{newcomer.full_name}"
                ),
            )

            messages.success(
                request,
                f"{newcomer.full_name}: пробное отменено",
            )

            return redirect("notifications")

        task = get_object_or_404(
            ManagerTask,
            pk=request.POST.get("task_id"),
        )

        if not can_complete_manager_task(
            request.user,
            task,
        ):
            return HttpResponseForbidden(
                "Это задача другого пользователя"
            )

        if task.is_done and not has_min_role(request.user, 2):
            return HttpResponseForbidden(
                "Возвращать выполненные задачи может только руководитель"
            )

        toggle_manager_task(
            task,
            request.user,
            request.POST.get(
                "completion_comment",
                "",
            ),
        )

        log_action(
            request,
            "task.toggle",
            task,
            (
                f"Задача «{task.title}»: "
                f"{'выполнена' if task.is_done else 'возвращена в работу'}"
            ),
        )

        messages.success(
            request,
            "Статус задачи изменён",
        )

        return redirect("notifications")

    # Последние уведомления пользователя
    event_notifications = list(
        Notification.objects
        .filter(recipient=request.user, resolved_at__isnull=True)
        .select_related("actor", "task")[:50]
    )
    

    unread_count = Notification.objects.filter(recipient=request.user, read_at__isnull=True, resolved_at__isnull=True).count()

    # Обычный список задач
    task_qs = ManagerTask.objects.filter(is_done=False)

    if not has_min_role(request.user, 2):
        task_qs = task_qs.filter(
            Q(assignee=request.user) | Q(assignee__isnull=True)
        )

    today = timezone.localdate()

    subscription_count = (
        Subscription.objects
        .filter(
            is_active=True,
            child__status=Child.Status.ACTIVE,
            end_date__range=(today, today + timedelta(days=7)),
        )
        .values("child_id")
        .distinct()
        .count()
    )

    today_trials = (
        Newcomer.objects
        .filter(
            trial_at__date=today,
            attended=False,
            lesson_cancelled=False,
            child__isnull=True,
        )
        .select_related(
            "trainer",
            "group",
        )
        .order_by("trial_at")
    )

    trial_count = today_trials.count()

    debt_count = Notification.objects.filter(
        recipient=request.user,
        kind=Notification.Kind.SUBSCRIPTION_DEBT,
        resolved_at__isnull=True,
    ).count()

    open_task_count = task_qs.count()

    return render(request, "crm/notifications.html", page_context(
        request, "notifications",
        subscription_count=subscription_count,
        event_notifications=event_notifications,
        unread_count=unread_count,
        debt_count=debt_count,
        today_trials=today_trials,
        open_task_count=open_task_count,
        trial_count=trial_count,
        open_count=(
            open_task_count
            + subscription_count
            + trial_count
            + debt_count
        ),
        today=today,
    ))

@login_required
@transaction.atomic
def applications_page(request):
    editing = Lead.objects.filter(pk=request.GET.get("edit")).first()
    form = LeadForm(request.POST or None, instance=editing)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "import_raw":
            raw = request.POST.get("raw_application", "")
            parsed = parse_application(raw)
            submitted_at = parsed.pop("submitted_at", None)
            if parsed.get("full_name"):
                parsed.setdefault("source", "Реклама")
                lead = Lead.objects.create(imported_from_ad=True, **parsed)
                if submitted_at is not None:
                    Lead.objects.filter(pk=lead.pk).update(
                        created_at=submitted_at,
                    )
                    lead.created_at = submitted_at

                notify_admins(
                    request.user,
                    Notification.Kind.LEAD_CREATED,
                    f"Новая заявка: {lead.full_name}",
                    f"{reverse('applications')}?edit={lead.pk}",
                )

                log_action(request, "lead.import", lead, f"Импортирована рекламная заявка {lead.full_name}")
                messages.success(request, "Заявка распознана и выделена как рекламная")
            else:
                messages.error(request, "Не удалось распознать имя. Используйте строку «Имя: ...»")
            return redirect("applications")
        if action == "create_newcomer":
            lead = get_object_or_404(Lead.objects.select_for_update(), pk=request.POST.get("lead_id"))
            if lead.newcomers.exists():
                messages.info(request, "Новичок из этой заявки уже создан")
                return redirect("newcomers")
            newcomer = Newcomer.objects.create(
                lead=lead,
                full_name=lead.full_name,
                birth_date=lead.birth_date,
                age_text=lead.age_text,
                phone=lead.phone,
                source=lead.source,
                trial_at=lead.trial_at,
                trainer=lead.trainer,
                group=lead.group,
                comment=lead.comment,
            )
            
            if newcomer.trial_at:
                trial_at = timezone.localtime(newcomer.trial_at)

                notify_admins(
                    request.user,
                    Notification.Kind.TRIAL_SCHEDULED,
                    f"Пробное: {newcomer.full_name} · {trial_at:%d.%m.%Y %H:%M}",
                    f"{reverse('newcomers')}?edit={newcomer.pk}",
                )
            
            lead.status = Lead.Status.QUALIFIED
            lead.save(update_fields=["status"])
            log_action(request, "lead.newcomer", newcomer, f"Из заявки создан новичок {newcomer.full_name}")
            messages.success(request, "Новичок создан и предзаполнен из заявки")
            return redirect("newcomers")
        if form.is_valid():
            lead = form.save()

            if not editing:
                notify_admins(
                    request.user,
                    Notification.Kind.LEAD_CREATED,
                    f"Новая заявка: {lead.full_name}",
                    f"{reverse('applications')}?edit={lead.pk}",
                )

            log_action(request, "lead.save", lead, f"Сохранена заявка {lead.full_name}")
            messages.success(request, "Заявка сохранена")
            return redirect("applications")
        messages.error(request, "Проверьте данные заявки")
    from django.db.models import Prefetch
    leads = Lead.objects.select_related("trainer", "group").prefetch_related(Prefetch("newcomers", queryset=Newcomer.objects.select_related("trainer", "group", "child").prefetch_related("child__payments")))
    return render(request, "crm/applications.html", page_context(
        request, "applications", leads=leads, form=form, editing=editing,
        imported_count=leads.filter(imported_from_ad=True, status=Lead.Status.NEW).count(),
    ))


@login_required
@transaction.atomic
def newcomers_page(request):
    editing = Newcomer.objects.filter(pk=request.GET.get("edit")).first()
    old_trial_at = editing.trial_at if editing else None
    form = NewcomerForm(request.POST or None, instance=editing)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "convert":
            newcomer = get_object_or_404(Newcomer, pk=request.POST.get("newcomer_id"))
            if newcomer.lead_id:
                Lead.objects.select_for_update().get(pk=newcomer.lead_id)
            newcomer = Newcomer.objects.select_for_update().get(pk=newcomer.pk)
            if newcomer.child:
                messages.info(request, "Карточка спортсмена уже создана")
                return redirect("newcomers")
            parts = newcomer.full_name.split()
            child = Child.objects.create(
                last_name=parts[0] if parts else "Без фамилии",
                first_name=parts[1] if len(parts) > 1 else "Без имени",
                patronymic=" ".join(parts[2:]),
                birth_date=newcomer.birth_date,
                birth_year=newcomer.birth_date.year if newcomer.birth_date else timezone.localdate().year - 7,
                parent_phone=newcomer.phone,
                group=newcomer.group,
                status=Child.Status.TRIAL,
                trial_from=timezone.localdate(),
                note=newcomer.comment,
            )
            newcomer.child = child
            newcomer.save(update_fields=["child"])
            if newcomer.lead:
                newcomer.lead.child = child
                newcomer.lead.save(update_fields=["child"])
            log_action(request, "newcomer.convert", child, f"Новичок {newcomer.full_name} перенесён в спортсмены")
            messages.success(
                request,
                "Карточка спортсмена создана. "
                "Если оплата получена — зафиксируйте её в продлениях.",
            )
            return redirect("payments")
            
        if form.is_valid():
            newcomer = form.save()

            trial_changed = (
                newcomer.trial_at
                and (
                    not old_trial_at
                    or newcomer.trial_at.replace(second=0, microsecond=0)
                    != old_trial_at.replace(second=0, microsecond=0)
                )
            )

            if trial_changed:
                trial_at = timezone.localtime(newcomer.trial_at)

                notify_admins(
                    request.user,
                    Notification.Kind.TRIAL_SCHEDULED,
                    f"Пробное: {newcomer.full_name} · {trial_at:%d.%m.%Y %H:%M}",
                    f"{reverse('newcomers')}?edit={newcomer.pk}",
                )

            log_action(request, "newcomer.save", newcomer, f"Сохранён новичок {newcomer.full_name}")
            messages.success(request, "Новичок сохранён")
            return redirect("newcomers")

        messages.error(request, "Проверьте данные новичка")
        
    return render(request, "crm/newcomers.html", page_context(
        request, "newcomers", newcomers=Newcomer.objects.select_related("lead", "trainer", "group", "child").prefetch_related("child__payments"),
        form=form, editing=editing,
    ))


@login_required
def calendar_page(request):
    today = timezone.localdate()
    now = timezone.now()
    can_manage_team_tasks = has_min_role(request.user, 2)

    try:
        anchor = date.fromisoformat(
            request.GET.get("start", "")
        )
    except (ValueError, TypeError):
        anchor = today

    month_start = anchor.replace(day=1)

    if month_start.month == 12:
        next_start = date(
            month_start.year + 1,
            1,
            1,
        )
    else:
        next_start = date(
            month_start.year,
            month_start.month + 1,
            1,
        )

    month_end = next_start - timedelta(days=1)

    if month_start.month == 1:
        prev_start = date(
            month_start.year - 1,
            12,
            1,
        )
    else:
        prev_start = date(
            month_start.year,
            month_start.month - 1,
            1,
        )

    # Календарная сетка начинается с понедельника
    # и заканчивается воскресеньем.
    grid_start = month_start - timedelta(
        days=month_start.weekday()
    )

    grid_end = month_end + timedelta(
        days=6 - month_end.weekday()
    )

    grid_days_count = (
        grid_end - grid_start
    ).days + 1

    try:
        selected_day = date.fromisoformat(
            request.GET.get("day", "")
        )
    except (ValueError, TypeError):
        selected_day = (
            today
            if month_start <= today <= month_end
            else month_start
        )

    scope = request.GET.get(
        "scope",
        "all" if can_manage_team_tasks else "mine",
    )

    state = request.GET.get(
        "state",
        "open",
    )

    if scope not in {
        "all",
        "mine",
    }:
        scope = "all" if can_manage_team_tasks else "mine"

    if state not in {
        "open",
        "done",
        "all",
    }:
        state = "open"

    if not can_manage_team_tasks:
        scope = "mine"
        state = "open"

    def back():
        return redirect(
            f"{reverse('calendar')}"
            f"?start={month_start.isoformat()}"
            f"&day={selected_day.isoformat()}"
            f"&scope={scope}"
            f"&state={state}"
        )

    editing = (
        ManagerTask.objects
        .filter(
            pk=request.GET.get("edit")
        )
        .first()
    )

    if editing and (
        not can_manage_manager_task(
            request.user,
            editing,
        )
        or (
            editing.is_done
            and not can_manage_team_tasks
        )
    ):
        return HttpResponseForbidden(
            "Недостаточно прав для редактирования этой задачи"
        )

    form = ManagerTaskForm(
        request.POST or None,
        instance=editing,
    )

    if request.method == "POST":
        action = request.POST.get(
            "action",
            "save",
        )

        if action == "toggle":
            task = get_object_or_404(
                ManagerTask,
                pk=request.POST.get(
                    "task_id"
                ),
            )

            if not can_complete_manager_task(
                request.user,
                task,
            ):
                return HttpResponseForbidden(
                    "Это задача другого пользователя"
                )

            if task.is_done and not can_manage_team_tasks:
                return HttpResponseForbidden(
                    "Возвращать выполненные задачи может только руководитель"
                )

            toggle_manager_task(
                task,
                request.user,
                request.POST.get(
                    "completion_comment",
                    "",
                ),
            )

            log_action(
                request,
                "task.toggle",
                task,
                (
                    f"Задача «{task.title}»: "
                    f"{'выполнена' if task.is_done else 'возвращена в работу'}"
                ),
            )

            messages.success(
                request,
                (
                    "Задача выполнена"
                    if task.is_done
                    else "Задача возвращена в работу"
                ),
            )

            return back()

        if action == "delete":
            task = get_object_or_404(
                ManagerTask,
                pk=request.POST.get(
                    "task_id"
                ),
            )

            if not can_manage_manager_task(
                request.user,
                task,
            ):
                return HttpResponseForbidden(
                    "Удалить чужую задачу "
                    "может только начальник"
                )

            if task.is_done and not can_manage_team_tasks:
                return HttpResponseForbidden(
                    "Удалять выполненные задачи может только руководитель"
                )

            title = task.title

            notify_task(
                task,
                request.user,
                Notification.Kind.TASK_DELETED,
            )

            log_action(
                request,
                "task.delete",
                task,
                (
                    f"Начальник удалил "
                    f"задачу «{title}»"
                ),
            )

            task.delete()

            messages.success(
                request,
                "Задача удалена",
            )

            return back()

        if action == "save":
            if form.is_valid():
                task = form.save(
                    commit=False
                )

                task.created_by = (
                    editing.created_by
                    if editing
                    else request.user
                )

                if not can_manage_team_tasks:
                    task.assignee = request.user

                task.save()

                notify_task(
                    task,
                    request.user,
                    (
                        Notification.Kind.TASK_UPDATED
                        if editing
                        else Notification.Kind.TASK_CREATED
                    ),
                )

                log_action(
                    request,
                    "task.save",
                    task,
                    (
                        f"{'Изменена' if editing else 'Создана'} "
                        f"задача «{task.title}»"
                    ),
                )

                messages.success(
                    request,
                    (
                        "Задача изменена"
                        if editing
                        else "Задача создана"
                    ),
                )

                return back()

            messages.error(
                request,
                "Проверьте поля задачи",
            )

    task_qs = ManagerTask.objects.select_related(
        "assignee",
        "created_by",
        "completed_by",
    )

    if not can_manage_team_tasks:
        task_qs = task_qs.filter(
            is_done=False,
        ).filter(
            Q(assignee=request.user) | Q(assignee__isnull=True)
        )

    tasks = list(
        task_qs.order_by(
            "scheduled_at",
            "due_date",
            "-created_at",
        )
    )

    def task_date(task):
        if task.scheduled_at:
            return timezone.localtime(
                task.scheduled_at
            ).date()

        return task.due_date

    for task in tasks:
        task.calendar_date = task_date(
            task
        )

        if task.is_done:
            task.is_overdue_now = False

        elif task.due_date:
            task.is_overdue_now = (
                task.due_date < today
            )

        elif task.scheduled_end_at:
            task.is_overdue_now = (
                task.scheduled_end_at < now
            )

        else:
            task.is_overdue_now = bool(
                task.scheduled_at
                and task.scheduled_at < now
            )

    filtered = tasks

    if scope == "mine":
        filtered = [
            task
            for task in filtered
            if task.assignee_id in (
                None,
                request.user.id,
            )
        ]

    if state == "open":
        filtered = [
            task
            for task in filtered
            if not task.is_done
        ]

    elif state == "done":
        filtered = [
            task
            for task in filtered
            if task.is_done
        ]

    def sort_tasks(items):
        return sorted(
            items,
            key=lambda task: (
                (
                    timezone.localtime(
                        task.scheduled_at
                    ).time()
                    if task.scheduled_at
                    else datetime.max.time()
                ),
                task.created_at,
            ),
        )

    days = []

    for offset in range(
        grid_days_count
    ):
        day = (
            grid_start
            + timedelta(days=offset)
        )

        items = sort_tasks([
            task
            for task in filtered
            if task.calendar_date == day
        ])

        days.append({
            "date": day,
            "month_start": day.replace(
                day=1
            ),
            "in_month": (
                day.month == month_start.month
                and day.year == month_start.year
            ),
            "items": items[:2],
            "task_count": len(items),
            "more_count": max(
                0,
                len(items) - 2,
            ),
        })

    selected_tasks = sort_tasks([
        task
        for task in filtered
        if task.calendar_date
        == selected_day
    ])

    undated_tasks = [
        task
        for task in filtered
        if task.calendar_date is None
    ]

    month_task_count = sum(
        1
        for task in filtered
        if (
            task.calendar_date
            and month_start
            <= task.calendar_date
            <= month_end
        )
    )

    return render(
        request,
        "crm/calendar.html",
        page_context(
            request,
            "calendar",
            form=form,
            editing=editing,
            days=days,
            month_start=month_start,
            month_end=month_end,
            selected_day=selected_day,
            selected_tasks=selected_tasks,
            undated_tasks=undated_tasks,
            month_task_count=month_task_count,
            prev_start=prev_start,
            next_start=next_start,
            today_start=today.replace(
                day=1
            ),
            today=today,
            scope=scope,
            state=state,
            can_manage_team_tasks=can_manage_team_tasks,
        ),
    )


@login_required
def search_page(request):
    query = request.GET.get("q", "").strip()
    children = leads = groups = []
    if query:
        children = Child.objects.filter(
            Q(last_name__icontains=query) | Q(first_name__icontains=query) |
            Q(parent_name__icontains=query) | Q(parent_phone__icontains=query)
        ).select_related("group")[:30]
        leads = Lead.objects.filter(Q(full_name__icontains=query) | Q(phone__icontains=query))[:30]
        groups = Group.objects.filter(Q(name__icontains=query) | Q(trainer__full_name__icontains=query))[:20]
    return render(request, "crm/search.html", page_context(
        request, "search", query=query, children=children, leads=leads, groups=groups,
    ))


@role_required(1)
def backup_export(request):
    output = StringIO()
    call_command("dumpdata", "crm", indent=2, stdout=output)
    response = HttpResponse(output.getvalue(), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="crm-backup-{timezone.localdate():%Y-%m-%d}.json"'
    log_action(request, "backup.export", None, "Выгружена резервная копия данных CRM")
    return response


@role_required(2)
def boss_page(request):
    today = timezone.localdate()
    now = timezone.now()
    month = today.replace(day=1)

    if month.month == 12:
        month_end = date(month.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = (
            date(month.year, month.month + 1, 1)
            - timedelta(days=1)
        )

    target = RevenueTarget.objects.filter(month=month).first()
    task_form = ManagerTaskForm(prefix="task")
    target_form = RevenueTargetForm(
        prefix="target",
        instance=target,
        initial={"month": month},
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_task":
            task_form = ManagerTaskForm(request.POST, prefix="task")
            if task_form.is_valid():
                task = task_form.save(commit=False)
                task.created_by = request.user
                task.save()

                notify_task(task, request.user, Notification.Kind.TASK_CREATED)
                log_action(request, "task.create", task, f"Поставлена задача «{task.title}»")
                messages.success(request, "Задача поставлена")
                return redirect("boss")

            messages.error(request, "Проверьте заполнение задачи")

        elif action == "reopen_task":
            task = get_object_or_404(ManagerTask, pk=request.POST.get("task_id"))

            if task.is_done:
                toggle_manager_task(task, request.user)
                log_action(request, "task.reopen", task, f"Задача «{task.title}» возвращена в работу")
                messages.success(request, "Задача возвращена в работу")

            task_filter = request.POST.get("task_filter", "done")
            return redirect(f"{reverse('boss')}?tasks={task_filter}#tasks")

        elif action == "delete_task":
            task = get_object_or_404(ManagerTask, pk=request.POST.get("task_id"))
            title = task.title

            log_action(request, "task.delete", task, f"Начальник удалил задачу «{title}»")
            task.delete()
            messages.success(request, "Задача удалена")

            task_filter = request.POST.get("task_filter", "active")
            return redirect(f"{reverse('boss')}?tasks={task_filter}#tasks")

        elif action == "set_target":
            target_month_raw = (request.POST.get("target-month") or "").strip()
            selected_target = None

            for date_format in ("%Y-%m", "%Y-%m-%d"):
                try:
                    selected_month = (
                        datetime.strptime(target_month_raw, date_format)
                        .date()
                        .replace(day=1)
                    )
                    selected_target = RevenueTarget.objects.filter(
                        month=selected_month,
                    ).first()
                    break
                except ValueError:
                    continue

            target_form = RevenueTargetForm(
                request.POST,
                prefix="target",
                instance=selected_target,
            )

            if target_form.is_valid():
                target = target_form.save(commit=False)
                target.set_by = request.user
                target.save()

                log_action(
                    request,
                    "revenue_target.save",
                    target,
                    f"Цель выручки: {target.amount} ₽",
                )
                messages.success(request, "Цель обновлена")
                return redirect("boss")

            messages.error(request, "Проверьте параметры цели")

    task_counts = ManagerTask.objects.aggregate(
        total=Count("pk"), done=Count("pk", filter=Q(is_done=True)),
        overdue=Count("pk", filter=Q(is_done=False) & (
            Q(due_date__lt=today) |
            Q(due_date__isnull=True, scheduled_end_at__lt=now) |
            Q(due_date__isnull=True, scheduled_end_at__isnull=True, scheduled_at__lt=now)
        )),
    )

    # Финансы. Текущая выручка — факт с начала месяца по сегодня.
    revenue = (
        Payment.objects
        .filter(
            date__gte=month,
            date__lte=today,
        )
        .aggregate(value=Sum("amount"))["value"]
        or Decimal("0")
    )

    forecast_rows = build_renewal_rows(
        month,
        month_end,
        today,
    )
    expected_revenue = sum(
        (row["amount"] for row in forecast_rows),
        Decimal("0"),
    )
    potential_revenue = Decimal(revenue) + expected_revenue

    target_amount = target.amount if target else Decimal("0")
    target_percent = (
        min(
            100,
            round(
                Decimal(revenue)
                * 100
                / target_amount
            ),
        )
        if target_amount
        else 0
    )

    salary_data = build_salary_data(month, month_end)
    salaries = salary_data["grand_total"]
    salary_paid = (
        SalaryPayout.objects
        .filter(month=month)
        .aggregate(value=Sum("amount"))["value"]
        or Decimal("0")
    )

    # KPI пробных занятий. Пробник = реально пришёл на пробное.
    trial_qs = (
        Newcomer.objects
        .filter(
            trial_at__date__gte=month,
            trial_at__date__lte=month_end,
            attended=True,
            lesson_cancelled=False,
        )
    )

    trial_by_trainer = {
        row["trainer_id"]: row["total"]
        for row in (
            trial_qs
            .exclude(trainer__isnull=True)
            .values("trainer_id")
            .annotate(total=Count("id"))
        )
    }
    retained_by_trainer = {
        row["trainer_id"]: row["total"]
        for row in (
            trial_qs
            .filter(child__payments__amount__gt=0)
            .exclude(trainer__isnull=True)
            .values("trainer_id")
            .annotate(total=Count("id", distinct=True))
        )
    }

    # KPI тренеров — посещаемость использует ту же формулу, что Глава 3.
    group_rows = build_group_stats(
        month,
        month_end,
        today,
    )
    trainer_rows = []

    active_by_trainer = dict(Child.objects.filter(status=Child.Status.ACTIVE).values("group__trainer_id").annotate(total=Count("pk")).values_list("group__trainer_id", "total"))
    lost_by_trainer = dict(Child.objects.filter(status__in=[Child.Status.LOST, Child.Status.ARCHIVED], archived_at__range=(month, month_end)).annotate(report_trainer=Coalesce("departure_trainer_id", "group__trainer_id")).values("report_trainer").annotate(total=Count("pk")).values_list("report_trainer", "total"))

    for trainer in _report_trainers(month, month_end):
        trainer_groups = [
            row
            for row in group_rows
            if row["group"].trainer_id == trainer.id
        ]

        present = sum(
            row["present"]
            for row in trainer_groups
        )
        capacity = sum(
            row["capacity"]
            for row in trainer_groups
        )
        trial = trial_by_trainer.get(
            trainer.id,
            0,
        )
        retained = retained_by_trainer.get(
            trainer.id,
            0,
        )
        lost = lost_by_trainer.get(trainer.pk, 0)

        trainer_rows.append({
            "trainer": trainer,
            "children": active_by_trainer.get(trainer.pk, 0),
            "trial": trial,
            "retained": retained,
            "retention_pct": (
                round(retained * 100 / trial)
                if trial
                else 0
            ),
            "lost": lost,
            "attendance_capacity": capacity,
            "attendance": (
                round(present * 100 / capacity)
                if capacity
                else 0
            ),
        })

    trainer_rows.sort(
        key=lambda row: (
            row["attendance"],
            row["retained"],
            row["children"],
        ),
        reverse=True,
    )

    # Топы Главы 6.
    top_trainers_attendance = [
        row
        for row in trainer_rows
        if row["attendance_capacity"] > 0
    ][:5]

    top_groups_attendance = sorted(
        [
            row
            for row in group_rows
            if row["capacity"] > 0
        ],
        key=lambda row: (
            row["attendance_pct"],
            row["present"],
        ),
        reverse=True,
    )[:5]

    top_trial_groups = [
        {
            "name": row["group__name"],
            "count": row["total"],
        }
        for row in (
            trial_qs
            .exclude(group__isnull=True)
            .values(
                "group_id",
                "group__name",
            )
            .annotate(total=Count("id"))
            .order_by(
                "-total",
                "group__name",
            )[:5]
        )
    ]

    top_competition_groups = [
        {
            "name": row["ranking_group_name"],
            "count": row["total"],
        }
        for row in (
            CompetitionEntry.objects
            .filter(
                competition__date__gte=month,
                competition__date__lte=month_end,
            )
            .annotate(
                ranking_group_id=Coalesce(
                    "group_snapshot_id",
                    "child__group_id",
                ),
                ranking_group_name=Coalesce(
                    "group_snapshot__name",
                    "child__group__name",
                ),
            )
            .filter(
                ranking_group_id__isnull=False,
            )
            .values(
                "ranking_group_id",
                "ranking_group_name",
            )
            .annotate(
                total=Count(
                    "child",
                    distinct=True,
                ),
            )
            .order_by(
                "-total",
                "ranking_group_name",
            )[:5]
        )
    ]

    # Журнал действий.
    all_logs = request.GET.get("all_logs") == "1"
    events_qs = (
        AuditEvent.objects
        .select_related("actor")
        .order_by("-created_at")
    )
    events_count = events_qs.count()
    from django.core.paginator import Paginator
    events_page = Paginator(events_qs, 100).get_page(request.GET.get("log_page")) if all_logs else None
    events = events_page.object_list if events_page else events_qs[:12]

    return render(
        request,
        "crm/boss.html",
        page_context(
            request,
            "boss",
            revenue=revenue,
            expected_revenue=expected_revenue,
            potential_revenue=potential_revenue,
            target=target,
            target_amount=target_amount,
            target_percent=target_percent,
            salaries=salaries,
            salary_paid=salary_paid,
            active_count=Child.objects.filter(
                status=Child.Status.ACTIVE,
            ).count(),
            trainer_rows=trainer_rows,
            top_trainers_attendance=top_trainers_attendance,
            top_groups_attendance=top_groups_attendance,
            top_trial_groups=top_trial_groups,
            top_competition_groups=top_competition_groups,
            events=events,
            events_count=events_count,
            events_page=events_page,
            all_logs=all_logs,

            overdue_tasks=task_counts["overdue"],
            task_active_count=task_counts["total"] - task_counts["done"],
            task_done_count=task_counts["done"],
            task_total_count=task_counts["total"],
            target_form=target_form,
        ),
    )


@role_required(2)
def boss_logs_export(request):
    """Полная выгрузка журнала действий начальнику."""
    today = timezone.localdate()

    log_action(
        request,
        "audit.export",
        None,
        "Выгружен полный журнал действий CRM",
    )

    events = (
        AuditEvent.objects
        .select_related("actor")
        .order_by("-created_at")
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Журнал действий"

    headers = [
        "Дата и время",
        "Сотрудник",
        "Действие",
        "Объект",
        "Описание",
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True)

    for event in events:
        actor = "Система"
        if event.actor:
            actor = (
                event.actor.get_full_name()
                or event.actor.username
            )

        object_label = ""
        if event.object_type:
            object_label = event.object_type
            if event.object_id:
                object_label += f" #{event.object_id}"

        ws.append([
            timezone.localtime(event.created_at).strftime(
                "%d.%m.%Y %H:%M:%S"
            ),
            actor,
            event.action,
            object_label,
            event.description,
        ])

    widths = {
        "A": 21,
        "B": 28,
        "C": 30,
        "D": 24,
        "E": 70,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    response = HttpResponse(
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="crm_audit_{today:%Y-%m-%d}.xlsx"'
    )
    wb.save(response)
    return response


def can_manage_staff_account(actor, target):
    if actor.pk == target.pk:
        return False
    if target.is_superuser and not actor.is_superuser:
        return False
    return user_rank(actor) >= user_rank(target)


@role_required(1)
def users_page(request):
    form = StaffCreateForm(
        request.POST or None,
        actor=request.user,
    )
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            if form.is_valid():
                user = form.save()
                log_action(request, "user.create", user, f"Создан пользователь {user.username}")
                messages.success(request, "Пользователь создан")
                return redirect("users")

        elif action == "toggle":
            user = get_object_or_404(
                get_user_model(),
                pk=request.POST.get("user_id"),
                is_staff=True,
            )
            if user == request.user:
                messages.error(request, "Нельзя отключить собственный аккаунт")
                return redirect("users")
            if not can_manage_staff_account(request.user, user):
                return HttpResponseForbidden(
                    "Недостаточно прав для управления этим аккаунтом"
                )

            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            log_action(
                request,
                "user.toggle",
                user,
                f"Аккаунт {user.username}: {'включён' if user.is_active else 'отключён'}",
            )
            messages.success(request, "Статус пользователя изменён")
            return redirect("users")

        messages.error(request, "Проверьте форму пользователя")

    users = get_user_model().objects.select_related("profile").filter(is_staff=True).order_by("-is_active", "last_name", "username")
    return render(request, "crm/users.html", page_context(request, "users", users=users, form=form))


@login_required
def profile_page(request):
    profile_form = ProfileForm(instance=request.user, prefix="profile")
    password_form = StyledPasswordChangeForm(request.user, prefix="password")
    if request.method == "POST":
        if request.POST.get("action") == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user, prefix="profile")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Профиль обновлён")
                return redirect("profile")
        elif request.POST.get("action") == "password":
            password_form = StyledPasswordChangeForm(request.user, request.POST, prefix="password")
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                log_action(request, "password.change", user, "Пользователь сменил пароль")
                messages.success(request, "Пароль изменён")
                return redirect("profile")
        messages.error(request, "Проверьте введённые данные")
    return render(request, "crm/profile.html", page_context(
        request, "profile", profile_form=profile_form, password_form=password_form,
    ))


from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import Child, Group

# views.py

from .models import Child, Group, calculate_projected_end_date # Не забудь импорт функции!

@login_required
def revenue_forecast_view(request):
    """Прогноз ближайших продлений на едином источнике расчёта."""
    today = timezone.localdate()
    horizon_end = today + timedelta(days=3)

    days_by_date = {}
    for i in range(4):
        current_date = today + timedelta(days=i)
        days_by_date[current_date] = {
            "date": current_date,
            "weekday": current_date.strftime("%A"),
            "total": Decimal("0"),
            "urgent": [],
            "one_left": [],
            "forecast": [],
        }

    # Используем тот же расчёт, что статистика и таблица продлений.
    rows = build_renewal_rows(
        today,
        horizon_end,
        today=today,
    )

    for row in rows:
        display_date = max(today, row["renewal_date"])
        day = days_by_date.get(display_date)
        if day is None:
            continue

        item = {
            "name": f"{row['child'].last_name} {row['child'].first_name}",
            "parent_name": row["parent_name"],
            "parent_phone": row["parent_phone"],
            "amount": row["amount"],
        }

        if row["renewal_date"] <= today or row["sessions_left"] <= 0:
            day["urgent"].append(item)
        elif row["sessions_left"] == 1:
            day["one_left"].append(item)
        else:
            day["forecast"].append(item)

        day["total"] += row["amount"]

    days = list(days_by_date.values())

    context = {
        "days": days,
        "title": "Прогноз доходов",
        "subtitle": "Ожидаемые продления на ближайшие 4 дня",
        "page": "revenue_forecast",
    }
    return render(request, "crm/revenue_forecast.html", context)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from .models import Child, Group, ScheduleSlot, Subscription, Attendance, ChildRank
from .forms import ChildForm, SubscriptionForm  # создадим ниже

@login_required
def child_card_view(request, child_id):
    child = get_object_or_404(Child, id=child_id)

    subscriptions = child.subscriptions.all().order_by('-start_date')
    attendances = (
        child.attendances
        .select_related("slot")
        .all()
        .order_by("-date", "-id")
    )
    ranks = child.ranks.all().order_by('-year')
    competitions = child.competition_entries.all().select_related('competition').order_by('-competition__date')[:20]
    camps = child.camp_stays.all().select_related('camp').order_by('-start_date')

    active_sub = child.active_subscription()
    sessions_left = child.sessions_left()
    debt = child.debt()
    balance = child.balance()
    missed_pct = child.missed_percent()
    nearest_exp = child.nearest_expiry()
    promos = child.active_promos()
    groups_list = Group.objects.filter(is_active=True)

    rank_form = ChildRankForm(
        prefix="rank",
        initial={"year": timezone.localdate().year},
    )
    camp_form = CampStayForm(prefix="camp")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_rank":
            rank_form = ChildRankForm(request.POST, prefix="rank")
            if rank_form.is_valid():
                ChildRank.objects.update_or_create(
                    child=child,
                    year=rank_form.cleaned_data["year"],
                    defaults={"rank": rank_form.cleaned_data["rank"]},
                )
                messages.success(request, "Спортивный разряд сохранён")
                return redirect("child_card", child_id=child.pk)

        elif action == "delete_rank":
            rank = get_object_or_404(
                child.ranks,
                pk=request.POST.get("rank_id"),
            )
            rank.delete()
            messages.success(request, "Разряд удалён")
            return redirect("child_card", child_id=child.pk)

        elif action == "add_camp":
            camp_form = CampStayForm(request.POST, prefix="camp")
            if camp_form.is_valid():
                camp_name = camp_form.cleaned_data["camp_name"].strip()
                camp = Camp.objects.filter(name__iexact=camp_name).first()
                if camp is None:
                    camp = Camp.objects.create(name=camp_name)

                CampStay.objects.get_or_create(
                    child=child,
                    camp=camp,
                    start_date=camp_form.cleaned_data["start_date"],
                    end_date=camp_form.cleaned_data["end_date"],
                )
                messages.success(request, "Поездка в лагерь сохранена")
                return redirect("child_card", child_id=child.pk)

        elif action == "delete_camp":
            stay = get_object_or_404(
                child.camp_stays,
                pk=request.POST.get("stay_id"),
            )
            stay.delete()
            messages.success(request, "Поездка удалена")
            return redirect("child_card", child_id=child.pk)

        elif action == "change_group" or "change_group" in request.POST:
            new_group_id = request.POST.get("new_group")
            if new_group_id:
                child.freeze_current_history()
                new_group = get_object_or_404(Group, id=new_group_id)
                child.group = new_group
                child.save(update_fields=["group"])
                # Личный график от старой группы не должен оставаться после перевода.
                child.schedule.clear()
                messages.success(
                    request,
                    f'Ребенок переведен в группу "{new_group.name}"',
                )
                return redirect("child_card", child_id=child.id)

    # === HEAT-MAP: последние 365 дней ===
        # === HEAT-MAP: последние 180 дней ===
    today = timezone.localdate()
    days_back = 90
    year_ago = today - timedelta(days=days_back - 1)

    # Получаем все посещения за период
    period_attendances = {
        att.date: att.status
        for att in child.attendances.filter(date__gte=year_ago)
    }
    attendance_labels = dict(Attendance.Status.choices)

    # Начинаем с понедельника (weekday() возвращает 0=Пн, 6=Вс)
    start_date = year_ago - timedelta(days=year_ago.weekday())
    end_date = today

    weeks = []
    current = start_date
    week_index = 0
    while current <= end_date:
        week = []
        week_start_date = current  # Понедельник этой недели
        for day_in_week in range(7):  # 0=Пн ... 6=Вс
            date = current + timedelta(days=day_in_week)
            if date > end_date or date < year_ago:
                week.append(None)
            else:
                status = period_attendances.get(date)
                week.append({
                    'date': date,
                    'status': status,
                    'status_label': attendance_labels.get(status, ''),
                    'is_future': date > today,
                })
        weeks.append({
            'days': week,
            'week_start': week_start_date,
            'show_label': week_index % 5 == 0,  # Каждый 5-й столбец
        })
        current += timedelta(days=7)
        week_index += 1

    # Статистика по статусам за период
    period_stats = {
        'present': sum(1 for s in period_attendances.values() if s == 'present'),
        'absent': sum(1 for s in period_attendances.values() if s == 'absent'),
        'frozen': sum(1 for s in period_attendances.values() if s == 'frozen'),
        'vacation': sum(1 for s in period_attendances.values() if s == 'vacation'),
        'excused': sum(1 for s in period_attendances.values() if s == 'excused'),
    }

    context = {
        'child': child,
        'subscriptions': subscriptions,
        'attendances': attendances,
        'ranks': ranks,
        'competitions': competitions,
        'camps': camps,
        'active_sub': active_sub,
        'sessions_left': sessions_left,
        'debt': debt,
        'balance': balance,
        'missed_percent': missed_pct,
        'nearest_expiry': nearest_exp,
        'promos': promos,
        'groups_list': groups_list,
        'weeks': weeks,
        'period_stats': period_stats,
        'today': today,
        'rank_form': rank_form,
        'camp_form': camp_form,
        'child_form': getattr(request, '_child_form', None) or ChildForm(instance=child),
        'editing_child_inline': hasattr(request, '_child_form'),
        'page': 'child_card'
    }
    return render(request, 'crm/child_card.html', context)


@login_required
def child_certificate_view(request, child_id):
    child = get_object_or_404(Child, id=child_id)
    if not child.certificate:
        raise Http404("Справка не прикреплена")

    content_type = (
        mimetypes.guess_type(child.certificate.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        child.certificate.open("rb"),
        content_type=content_type,
    )


@login_required
def child_edit_view(request, child_id):
    child = get_object_or_404(
        Child,
        id=child_id,
    )

    if request.method == "POST":
        old_status = child.status
        old_group = child.group
        old_trainer = child.trainer

        # Фиксируем историю до возможной смены группы/статуса.
        child.freeze_current_history()

        form = ChildForm(
            request.POST,
            request.FILES,
            instance=child,
        )

        if form.is_valid():
            child = form.save(commit=False)

            # Если ребёнок больше не на пробном,
            # дата начала пробного периода больше не нужна.
            if child.status != Child.Status.TRIAL:
                child.trial_from = None

            departed_statuses = (
                Child.Status.LOST,
                Child.Status.ARCHIVED,
            )

            if child.status in departed_statuses:
                if old_status not in departed_statuses:
                    child.archived_at = timezone.localdate()
                    child.departure_group = old_group
                    child.departure_trainer = old_trainer
            elif old_status in departed_statuses:
                child.archived_at = None
                child.departure_group = None
                child.departure_trainer = None

            child.save()
            form.save_m2m()

            if old_group and old_group.pk != child.group_id:
                child.schedule.clear()

            log_action(
                request,
                "child.update",
                child,
                f"Обновлена карточка спортсмена {child}",
            )

            messages.success(
                request,
                "Данные ребёнка обновлены",
            )

            next_url = (
                request.POST.get("next")
                or reverse(
                    "child_card",
                    args=[child.pk],
                )
            )

            return redirect(next_url)

        messages.error(
            request,
            "Проверьте заполнение карточки",
        )

    else:
        form = ChildForm(
            instance=child,
        )

    if request.POST.get("inline") == "1":
        request._child_form = form
        return child_card_view(request, child_id)

    return render(
        request,
        "crm/child_edit.html",
        {
            "form": form,
            "child": child,
            "page": "child_edit",
        },
    )


@login_required
def child_create_view(request):
    if request.method == 'POST':
        form = ChildForm(request.POST, request.FILES)
        if form.is_valid():
            child = form.save()
            messages.success(request, f'Ребенок {child.last_name} {child.first_name} добавлен')
            return redirect('child_card', child_id=child.id)
    else:
        form = ChildForm()
    return render(request, 'crm/child_edit.html', {'form': form, 'page': 'child_create'})

@login_required
def child_delete_view(request, child_id):
    child = get_object_or_404(Child, id=child_id)
    if request.method == 'POST':
        child_name = f"{child.last_name} {child.first_name}"
        child.delete()
        messages.success(request, f'Ребенок {child_name} удален')
        return redirect('attendance')
    return render(request, 'crm/child_delete.html', {'child': child, 'page': 'child_delete'})



@login_required
def add_subscription_view(request, child_id):
    child = get_object_or_404(Child, id=child_id)
    if request.method != "POST":
        return redirect(f"{reverse('payments')}?child={child.pk}&new_subscription=1")
    form = SubscriptionForm(request.POST, initial={"child": child})
    form.fields["child"].disabled = True
    if form.is_valid():
        sub = form.save()
        messages.success(request, "Абонемент добавлен")
        return redirect("child_card", child_id=child.pk)
    return render(request, "crm/add_subscription.html", {"form": form, "child": child, "page": "add_subscription"})


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Trainer, Group, ScheduleSlot
from .forms import TrainerForm, GroupForm, ScheduleSlotFormSet

# ==================== ТРЕНЕРЫ ====================

@login_required
def trainer_list_view(request):
    """Список тренеров и встроенное редактирование."""
    if request.GET.get("edit") or request.GET.get("create"):
        request._inline_trainer = True
        return trainer_edit_view(request, request.GET["edit"]) if request.GET.get("edit") else trainer_create_view(request)
    trainers = Trainer.objects.all().prefetch_related('groups').order_by('full_name')
    context = {
        'trainers': trainers,
        'title': 'Тренеры',
        'subtitle': 'Управление тренерским составом',
        'page': 'trainers'
    }
    return render(request, 'crm/trainers.html', context)

@login_required
def trainer_create_view(request):
    """Создание тренера"""
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
    if getattr(request, "_inline_trainer", False):
        context["form_title"] = context["title"]
        context["title"] = "Тренеры"
        context["trainers"] = Trainer.objects.prefetch_related("groups").order_by("full_name")
        return render(request, "crm/trainers.html", context)
    return render(request, 'crm/trainer_edit.html', context)

@login_required
def trainer_edit_view(request, pk):
    """Редактирование тренера"""
    trainer = get_object_or_404(Trainer, pk=pk)
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
    if getattr(request, "_inline_trainer", False):
        context["form_title"] = context["title"]
        context["title"] = "Тренеры"
        context["trainers"] = Trainer.objects.prefetch_related("groups").order_by("full_name")
        return render(request, "crm/trainers.html", context)
    return render(request, 'crm/trainer_edit.html', context)

@login_required
def trainer_delete_view(request, pk):
    """Удаление тренера"""
    trainer = get_object_or_404(Trainer, pk=pk)
    if request.method == 'POST':
        # Проверяем, есть ли группы у тренера
        if trainer.groups.exists():
            messages.error(request, f'Нельзя удалить тренера {trainer.full_name}: у него есть группы. Сначала удалите или переназначьте группы.')
            return redirect('trainer_list')
        trainer.delete()
        messages.success(request, f'Тренер {trainer.full_name} удален')
        return redirect('trainer_list')

    context = {
        'trainer': trainer,
        'title': 'Удаление тренера',
        'page': 'trainers'
    }
    return render(request, 'crm/trainer_delete.html', context)


# ==================== ГРУППЫ ====================

@login_required
def group_list_view(request):
    """Список групп и встроенное редактирование."""
    if request.GET.get("edit") or request.GET.get("create"):
        request._inline_group = True
        return group_edit_view(request, request.GET["edit"]) if request.GET.get("edit") else group_create_view(request)
    groups = Group.objects.select_related('trainer').prefetch_related('schedule', 'children').order_by('trainer__full_name', 'trainer_id', 'name')
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
    if getattr(request, "_inline_group", False):
        context["form_title"] = context["title"]
        context["title"] = "Группы"
        context["groups"] = Group.objects.select_related("trainer").prefetch_related("schedule", "children").order_by("trainer__full_name", "trainer_id", "name")
        return render(request, "crm/groups.html", context)
    return render(request, 'crm/group_edit.html', context)

@login_required
def group_edit_view(request, pk):
    """Редактирование группы с расписанием"""
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        # До изменения тренера/ставки фиксируем старые посещения.
        for child in group.children.select_related("group__trainer"):
            child.freeze_current_history()

        group_form = GroupForm(request.POST, instance=group)
        slot_formset = ScheduleSlotFormSet(request.POST, instance=group)

        if group_form.is_valid() and slot_formset.is_valid():
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
    if getattr(request, "_inline_group", False):
        context["form_title"] = context["title"]
        context["title"] = "Группы"
        context["groups"] = Group.objects.select_related("trainer").prefetch_related("schedule", "children").order_by("trainer__full_name", "trainer_id", "name")
        return render(request, "crm/groups.html", context)
    return render(request, 'crm/group_edit.html', context)

@login_required
def group_delete_view(request, pk):
    """Удаление группы"""
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        children_count = group.children.count()
        if children_count > 0:
            messages.error(request, f'Нельзя удалить группу "{group.name}": в ней {children_count} детей. Сначала переведите детей в другие группы.')
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


from datetime import date, timedelta, datetime
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.http import HttpResponse

def _month_range(request):
    today = timezone.localdate()
    month_raw = (request.GET.get("month") or "").strip()

    month_start = today.replace(day=1)

    if month_raw:
        for date_format in ("%Y-%m", "%Y-%m-%d"):
            try:
                month_start = (
                    datetime.strptime(
                        month_raw,
                        date_format,
                    )
                    .date()
                    .replace(day=1)
                )
                break
            except ValueError:
                continue

    if month_start.month == 12:
        month_end = date(
            month_start.year + 1,
            1,
            1,
        ) - timedelta(days=1)
    else:
        month_end = date(
            month_start.year,
            month_start.month + 1,
            1,
        ) - timedelta(days=1)

    return month_start, month_end, today

def _sessions_held(group, month_start, month_end, today):
    """Сколько дней занятий прошло по расписанию группы в месяце."""
    weekdays = set(
        ScheduleSlot.objects
        .filter(group=group)
        .values_list("weekday", flat=True)
    )
    last = min(month_end, today)
    count, d = 0, month_start

    while d <= last:
        if d.weekday() in weekdays:
            count += 1
        d += timedelta(days=1)

    return count


def _attendance_for_group(group, month_start, month_end):
    """Отметки текущих спортсменов, относящиеся именно к этой группе."""
    current_statuses = (
        Child.Status.ACTIVE,
        Child.Status.TRIAL,
    )

    return (
        Attendance.objects
        .filter(
            child__group=group,
            child__status__in=current_statuses,
            date__gte=month_start,
            date__lte=month_end,
        )
        .filter(
            Q(group_snapshot=group)
            | Q(group_snapshot__isnull=True)
        )
    )


def _report_trainers(month_start, month_end):
    """Активные тренеры плюс тренеры с показателями в выбранном периоде."""
    trainer_ids = set(
        Trainer.objects
        .filter(is_active=True)
        .values_list("pk", flat=True)
    )

    trainer_ids.update(
        Group.objects
        .filter(is_active=True)
        .values_list("trainer_id", flat=True)
    )

    trainer_ids.update(
        Newcomer.objects
        .filter(
            trial_at__date__gte=month_start,
            trial_at__date__lte=month_end,
            attended=True,
            lesson_cancelled=False,
            trainer__isnull=False,
        )
        .values_list("trainer_id", flat=True)
    )

    trainer_ids.update(
        Child.objects
        .filter(
            status__in=[Child.Status.LOST, Child.Status.ARCHIVED],
            archived_at__gte=month_start,
            archived_at__lte=month_end,
            departure_trainer__isnull=False,
        )
        .values_list("departure_trainer_id", flat=True)
    )

    trainer_ids.update(
        Attendance.objects
        .filter(
            date__gte=month_start,
            date__lte=month_end,
            trainer_snapshot__isnull=False,
        )
        .values_list("trainer_snapshot_id", flat=True)
    )

    return Trainer.objects.filter(
        pk__in=trainer_ids,
    ).order_by("full_name")


def build_group_stats(month_start, month_end, today):
    """Единая формула посещаемости; суммы считаются пакетно."""
    from django.db.models import F
    current_statuses = (Child.Status.ACTIVE, Child.Status.TRIAL)
    kids_by_group = dict(Child.objects.filter(status__in=current_statuses).values("group_id").annotate(total=Count("pk")).values_list("group_id", "total"))
    totals = {(row["child__group_id"], row["status"]): row["total"] for row in Attendance.objects.filter(
        child__status__in=current_statuses, date__range=(month_start, month_end),
    ).filter(Q(group_snapshot_id=F("child__group_id")) | Q(group_snapshot__isnull=True)).values("child__group_id", "status").annotate(total=Count("pk"))}
    result = []
    for group in Group.objects.filter(is_active=True).select_related("trainer").prefetch_related("schedule"):
        kids = kids_by_group.get(group.pk, 0)
        weekdays = {slot.weekday for slot in group.schedule.all()}
        sessions = sum((month_start + timedelta(days=offset)).weekday() in weekdays for offset in range(max(0, (min(month_end, today) - month_start).days + 1)))
        present = totals.get((group.pk, Attendance.Status.PRESENT), 0)
        absent = totals.get((group.pk, Attendance.Status.ABSENT), 0)
        capacity = kids * sessions
        result.append({"group": group, "kids": kids, "present": present, "absent": absent, "sessions": sessions,
                       "capacity": capacity, "attendance_pct": round(present * 100 / capacity) if capacity else 0})
    return result


def build_salary_data(month_start, month_end):
    """ЗП по историческим снимкам группы, тренера и ставки."""
    buckets = {}
    present_marks = (
        Attendance.objects
        .filter(
            status=Attendance.Status.PRESENT,
            date__gte=month_start,
            date__lte=month_end,
        )
        .select_related(
            "child__group__trainer",
            "group_snapshot",
            "trainer_snapshot",
        )
    )

    for mark in present_marks:
        group = mark.group_snapshot or mark.child.group
        trainer = mark.trainer_snapshot or (group.trainer if group else None)
        if not group or not trainer:
            continue

        rate = (
            mark.salary_rate_snapshot
            if mark.salary_rate_snapshot is not None
            else group.salary_rate
        ) or Decimal("0")
        rate = Decimal(rate)

        key = (trainer.pk, group.pk, rate)
        row = buckets.setdefault(
            key,
            {
                "trainer": trainer,
                "group": group,
                "rate": rate,
                "visits": 0,
            },
        )
        row["visits"] += 1

    trainer_map = {}
    summary_rows = []
    grand_total = Decimal("0")

    for row in sorted(
        buckets.values(),
        key=lambda item: (
            item["trainer"].full_name,
            item["group"].name,
            item["rate"],
        ),
    ):
        total = row["rate"] * row["visits"]
        trainer_data = trainer_map.setdefault(
            row["trainer"].pk,
            {
                "trainer": row["trainer"],
                "rows": [],
                "total": Decimal("0"),
            },
        )
        salary_row = {
            "name": row["group"].name,
            "rate": row["rate"],
            "visits": row["visits"],
            "total": total,
            "is_adjustment": False,
            "adjustment_id": None,
        }
        trainer_data["rows"].append(salary_row)
        trainer_data["total"] += total
        summary_rows.append(salary_row)
        grand_total += total

    adjustments = (
        SalaryAdjustment.objects
        .filter(month=month_start)
        .select_related("trainer")
        .order_by("trainer__full_name", "title", "pk")
    )

    for adjustment in adjustments:
        trainer_data = trainer_map.setdefault(
            adjustment.trainer_id,
            {
                "trainer": adjustment.trainer,
                "rows": [],
                "total": Decimal("0"),
            },
        )
        salary_row = {
            "name": adjustment.title,
            "rate": "",
            "visits": "",
            "total": adjustment.amount,
            "is_adjustment": True,
            "adjustment_id": adjustment.pk,
        }
        trainer_data["rows"].append(salary_row)
        trainer_data["total"] += adjustment.amount
        summary_rows.append(salary_row)
        grand_total += adjustment.amount

    trainers = sorted(
        trainer_map.values(),
        key=lambda item: item["trainer"].full_name,
    )
    return {
        "summary_rows": summary_rows,
        "grand_total": grand_total,
        "trainers": trainers,
    }


@login_required
def statistics_view(request):
    month_start, month_end, today = _month_range(request)

    children = Child.objects.all()
    current_statuses = (
        Child.Status.ACTIVE,
        Child.Status.TRIAL,
    )
    total_children = children.filter(
        status__in=current_statuses,
    ).count()
    active_children = children.filter(status=Child.Status.ACTIVE).count()
    unassigned_children = (
        children
        .filter(status__in=current_statuses)
        .filter(
            Q(group__isnull=True)
            | Q(group__is_active=False)
        )
        .count()
    )

    new_qs = children.filter(created_at__date__gte=month_start, created_at__date__lte=month_end)
    new_count = new_qs.count()
    new_kept = new_qs.filter(status__in=current_statuses).count()
    left_count = children.filter(
        status__in=[Child.Status.LOST, Child.Status.ARCHIVED],
        archived_at__gte=month_start, archived_at__lte=month_end).count()

    if month_start > today:
        revenue_to_date = Decimal("0")
    else:
        revenue_cutoff = min(month_end, today)
        revenue_to_date = (
            Payment.objects
            .filter(
                date__gte=month_start,
                date__lte=revenue_cutoff,
            )
            .aggregate(s=Sum("amount"))["s"]
            or Decimal("0")
        )

    revenue_month = Payment.objects.filter(
        date__gte=month_start, date__lte=month_end).aggregate(s=Sum('amount'))['s'] or 0

    forecast_rows = build_renewal_rows(
        month_start,
        month_end,
        today,
    )
    expected = sum(
        (row["amount"] for row in forecast_rows),
        Decimal("0"),
    )
    potential = Decimal(revenue_month) + expected

    target = RevenueTarget.objects.filter(month=month_start).first()
    target_percent = (
        min(100, round(Decimal(revenue_month) * 100 / target.amount))
        if target and target.amount
        else 0
    )
    expenses_month = (
        Expense.objects
        .filter(date__gte=month_start, date__lte=month_end)
        .aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )

    groups_stats = build_group_stats(
        month_start,
        month_end,
        today,
    )

    trainers_stats = []
    for t in _report_trainers(month_start, month_end):
        t_left = children.filter(
            Q(departure_trainer=t)
            | Q(departure_trainer__isnull=True, group__trainer=t),
            status__in=[Child.Status.LOST, Child.Status.ARCHIVED],
            archived_at__gte=month_start,
            archived_at__lte=month_end,
        ).distinct().count()
        t_groups = [gs for gs in groups_stats if gs['group'].trainer_id == t.id]
        t_present = sum(gs['present'] for gs in t_groups)
        t_capacity = sum(gs['capacity'] for gs in t_groups)
        trainers_stats.append({
            'trainer': t,
            'left': t_left,
            'present': t_present,
            'attendance_pct': round(t_present * 100 / t_capacity) if t_capacity else 0,
        })

    context = {
        'month_start': month_start, 'month_end': month_end, 'today': today,
        'total_children': total_children, 'active_children': active_children,
        'unassigned_children': unassigned_children,
        'new_count': new_count, 'new_kept': new_kept,
        'left_count': left_count,
        'revenue_to_date': revenue_to_date,
        # Совместимость со старым именем контекста.
        'revenue_today': revenue_to_date,
        'revenue_month': revenue_month,
        'potential': potential, 'expected': expected,
        'target': target, 'target_percent': target_percent,
        'previous_month': (month_start - timedelta(days=1)).strftime('%Y-%m'),
        'next_month': (month_end + timedelta(days=1)).strftime('%Y-%m'),
        'bar_scale': max(Decimal(revenue_month), potential, target.amount if target else 0, Decimal(1)),
        'expenses_month': expenses_month,
        'groups_stats': groups_stats, 'trainers_stats': trainers_stats,
        'title': 'Статистика', 'page': 'statistics',
    }
    return render(request, 'crm/statistics.html', context)


@role_required(1)
def salaries_view(request):
    month_start, month_end, today = _month_range(request)
    can_manage_salary = has_min_role(request.user, 1)
    adjustment_form = SalaryAdjustmentForm(prefix="adjustment")

    if request.method == "POST":
        if not can_manage_salary:
            return HttpResponseForbidden(
                "Изменять ручные строки ЗП может только старший администратор или начальник"
            )

        action = request.POST.get("action")
        if action == "add_adjustment":
            adjustment_form = SalaryAdjustmentForm(
                request.POST,
                prefix="adjustment",
            )
            if adjustment_form.is_valid():
                adjustment = adjustment_form.save(commit=False)
                adjustment.month = month_start
                adjustment.save()
                messages.success(request, "Строка ЗП добавлена")
                return redirect(
                    f"{reverse('salaries')}?month={month_start:%Y-%m}"
                )
            messages.error(request, "Проверьте ручную строку ЗП")

        elif action == "delete_adjustment":
            adjustment = get_object_or_404(
                SalaryAdjustment,
                pk=request.POST.get("adjustment_id"),
                month=month_start,
            )
            adjustment.delete()
            messages.success(request, "Строка ЗП удалена")
            return redirect(
                f"{reverse('salaries')}?month={month_start:%Y-%m}"
            )

    data = build_salary_data(month_start, month_end)
    context = {
        **data,
        'month_start': month_start,
        'month_end': month_end,
        'can_manage_salary': can_manage_salary,
        'adjustment_form': adjustment_form,
        'title': 'ЗП тренеров',
        'page': 'salaries',
    }
    return render(request, 'crm/salaries.html', context)


@role_required(1)
def salaries_export_view(request):
    """Выгрузка таблицы ЗП в Excel (формат как в ручном подсчете)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    month_start, month_end, today = _month_range(request)
    data = build_salary_data(month_start, month_end)

    wb = Workbook()
    ws = wb.active
    ws.title = 'ЗП тренеров'

    thin = Side(style='thin', color='000000')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    green = PatternFill('solid', fgColor='92D050')
    gray = PatternFill('solid', fgColor='E2EFDA')
    bold = Font(bold=True)
    center = Alignment(horizontal='center')

    ws.merge_cells('A1:D1')
    ws['A1'] = f"{month_start:%d.%m.%Y} — {month_end:%d.%m.%Y}"
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = center

    row = 3
    for header, col in [('Группа', 'A'), ('Ставка', 'B'), ('Посещение', 'C'), ('Всего', 'D')]:
        c = ws[f'{col}{row}']; c.value = header; c.font = bold; c.border = border; c.fill = gray
    row += 1

    for r in data['summary_rows']:
        ws[f'A{row}'] = r['name']; ws[f'B{row}'] = r['rate']
        ws[f'C{row}'] = r['visits']; ws[f'D{row}'] = r['total']
        for col in 'ABCD': ws[f'{col}{row}'].border = border
        row += 1

    ws[f'A{row}'] = 'Итого'; ws[f'A{row}'].font = bold
    ws[f'D{row}'] = data['grand_total']; ws[f'D{row}'].font = bold
    ws[f'D{row}'].fill = gray
    for col in 'ABCD': ws[f'{col}{row}'].border = border
    row += 2

    for t in data['trainers']:
        ws.merge_cells(f'A{row}:D{row}')
        ws[f'A{row}'] = t['trainer'].full_name
        ws[f'A{row}'].font = bold; ws[f'A{row}'].fill = green
        for col in 'BCD': ws[f'{col}{row}'].fill = green
        row += 1
        for r in t['rows']:
            ws[f'A{row}'] = r['name']; ws[f'B{row}'] = r['rate']
            ws[f'C{row}'] = r['visits']; ws[f'D{row}'] = r['total']
            for col in 'ABCD': ws[f'{col}{row}'].border = border
            row += 1
        ws[f'C{row}'] = 'Итого'; ws[f'C{row}'].font = bold
        ws[f'D{row}'] = t['total']; ws[f'D{row}'].font = bold
        row += 2

    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 12
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 12

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="salaries_{month_start:%Y-%m}.xlsx"'
    wb.save(response)
    return response


def _prepaid_credit(child):
    """Свободная предоплата после покрытия неотменённых начислений."""
    return max(Decimal("0"), child.balance())


def build_renewal_rows(month_start, month_end, today=None):
    """Кому и когда звонить по продлению абонемента."""
    today = today or timezone.localdate()
    rows = []
    is_current_month = month_start <= today <= month_end

    children = (
        Child.objects
        .filter(status=Child.Status.ACTIVE)
        .select_related("group")
        .prefetch_related("subscriptions__tariff", "payments", "attendances", "group__schedule")
    )

    for child in children:
        subscriptions = [sub for sub in child.subscriptions.all() if sub.is_active and not sub.cancelled_at]
        if any(sub.start_date > today for sub in subscriptions):
            continue
        active_subscription = child.active_subscription()
        subscription = active_subscription or max((sub for sub in subscriptions if sub.start_date <= today), key=lambda sub: (sub.end_date, sub.pk), default=None)

        if not subscription:
            continue

        sessions_left = child.sessions_left() if active_subscription else 0
        projected_end = (
            child.projected_end_date()
            if active_subscription and sessions_left > 0
            else None
        )

        end_candidates = [subscription.end_date]
        if projected_end:
            end_candidates.append(projected_end)

        renewal_date = (
            today
            if active_subscription and sessions_left <= 0
            else min(end_candidates)
        )
        call_date = renewal_date - timedelta(days=3)

        if is_current_month:
            # В текущем месяце не теряем просроченные незакрытые продления.
            if renewal_date > month_end:
                continue
        elif not (month_start <= renewal_date <= month_end):
            continue

        if renewal_date <= today or sessions_left <= 0:
            priority = 0
            status = "Срочно"
        elif call_date <= today:
            priority = 1
            status = "Позвонить сегодня"
        elif call_date <= today + timedelta(days=3):
            priority = 2
            status = "В ближайшие 3 дня"
        else:
            priority = 3
            status = "Запланировано"

        renewal_price = Decimal(
            subscription.tariff.price
            if subscription.tariff
            else subscription.price
        )
        prepaid_credit = min(
            _prepaid_credit(child),
            renewal_price,
        )
        amount = max(
            Decimal("0"),
            renewal_price - prepaid_credit,
        )

        # Продление уже полностью оплачено заранее — звонить не нужно,
        # и в прогнозную выручку его второй раз не включаем.
        if amount <= 0:
            continue

        rows.append({
            "child": child,
            "group": child.group,
            "parent_name": child.parent_name,
            "parent_phone": child.parent_phone,
            "subscription": subscription,
            "sessions_left": sessions_left,
            "projected_end": projected_end,
            "renewal_date": renewal_date,
            "call_date": call_date,
            "renewal_price": renewal_price,
            "prepaid_credit": prepaid_credit,
            "amount": amount,
            "priority": priority,
            "status": status,
        })

    rows.sort(
        key=lambda row: (
            row["priority"],
            row["call_date"],
            row["renewal_date"],
            row["child"].last_name,
        )
    )
    return rows



@login_required
def payment_history_view(request):
    month_start, month_end, today = _month_range(request)
    payments = Payment.objects.filter(
        date__gte=month_start,
        date__lte=month_end,
    ).select_related(
        'child',
        'child__group',
        'created_by',
        'subscription',
    ).order_by('-date')

    total = payments.aggregate(s=Sum('amount'))['s'] or 0
    context = {
        'payments': payments,
        'total': total,
        'month_start': month_start,
        'month_end': month_end,
        'title': 'История оплат',
        'page': 'payment_history',
    }
    return render(request, 'crm/payment_history.html', context)




@login_required
@require_POST
def cancel_subscription_view(request):
    with transaction.atomic():
        subscription = get_object_or_404(
            Subscription.objects.select_for_update(),
            pk=request.POST.get("subscription_id"), child_id=request.POST.get("child_id"),
        )
        if request.POST.get("confirmed") != "1":
            return JsonResponse({"status": "error", "message": "Подтвердите отмену"}, status=400)
        if subscription.cancelled_at is None and not subscription.is_active:
            return JsonResponse({"status": "error", "message": "Абонемент уже изменён. Обновите табель"}, status=409)
        subscription.cancel()
        log_action(request, "subscription.cancel", subscription, f"Отменён абонемент {subscription}")
    return JsonResponse({"status": "ok"})


@login_required
def camps_page(request):
    editing = get_object_or_404(Camp, pk=request.GET["edit"]) if request.GET.get("edit") else None
    legacy_camp = editing is not None and (editing.start_date is None or editing.end_date is None)
    form = CampEventForm(request.POST or None, instance=editing)
    if request.method == "POST" and form.is_valid():
        if legacy_camp:
            legacy_dates = set(editing.campstay_set.values_list("start_date", "end_date"))
            if len(legacy_dates) > 1:
                form.add_error(None, "У этого исторического лагеря несколько заездов. Создайте отдельное мероприятие: старые поездки сохранятся в карточках.")
        if not form.errors:
            return _save_camp_event(request, form)
    return render(request, "crm/camps.html", page_context(request, "camps", title="Лагеря и сборы", camps=Camp.objects.annotate(participant_count=Count("campstay__child", distinct=True)).order_by("-start_date", "name"), form=form, editing=editing))


def _save_camp_event(request, form):
    with transaction.atomic():
        camp = form.save()
        selected_ids = set(form.cleaned_data["children"].values_list("pk", flat=True))
        # Editing the roster changes only this event's trips.
        CampStay.objects.filter(camp=camp).exclude(child_id__in=selected_ids).delete()
        for child_id in selected_ids:
            stays = CampStay.objects.filter(camp=camp, child_id=child_id)
            if stays.exists():
                stays.update(start_date=camp.start_date, end_date=camp.end_date)
            else:
                CampStay.objects.create(camp=camp, child_id=child_id, start_date=camp.start_date, end_date=camp.end_date)
        log_action(request, "camp.save", camp, f"Мероприятие {camp}: {len(selected_ids)} участников")
    messages.success(request, "Мероприятие и состав участников сохранены")
    return redirect("camps")


@login_required
def competition_document_download(request, pk):
    from django.http import FileResponse, Http404
    from pathlib import Path
    document = get_object_or_404(CompetitionDocument, pk=pk)
    try:
        response = FileResponse(document.file.open("rb"), as_attachment=True, filename=Path(document.file.name).name)
    except (FileNotFoundError, ValueError):
        raise Http404("Файл не найден")
    response["X-Content-Type-Options"] = "nosniff"
    return response
