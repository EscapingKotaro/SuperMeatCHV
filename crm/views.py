from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import StringIO

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .forms import (
    ApparatusForm,
    ChildForm,
    CompetitionEntryForm,
    CompetitionForm,
    ExpenseForm,
    LeadForm,
    ManagerTaskForm,
    NewcomerForm,
    ProfileForm,
    ReminderForm,
    RevenueTargetForm,
    StaffCreateForm,
    StyledPasswordChangeForm,
    SubscriptionForm,
    TariffForm,
)
from .models import (
    Apparatus,
    ApparatusScore,
    Attendance,
    AuditEvent,
    Child,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    ManagerTask,
    Newcomer,
    Payment,
    Reminder,
    RevenueTarget,
    Role,
    SalaryPayout,
    StaffProfile,
    Subscription,
    Tariff,
    Trainer,
    user_role,
)


PAGE_META = {
    "attendance": ("Табель", "Отмечайте посещения прямо в таблице"),
    "statistics": ("Статистика", "Главные показатели клуба"),
    "payments": ("Продления", "Кому пора напомнить об оплате"),
    "expenses": ("Расходы", "Бытовые закупки и другие расходы"),
    "competitions": ("Соревнования", "Баллы, места и история выступлений"),
    "notifications": ("Уведомления", "Задачи и события, требующие внимания"),
    "boss": ("Для руководителя", "Выручка, KPI и работа команды"),
    "users": ("Пользователи", "Доступы сотрудников и роли"),
    "profile": ("Мой профиль", "Личные данные и безопасность"),
    "applications": ("Заявки", "Все обращения из рекламы, сайта и звонков"),
    "newcomers": ("Новички", "Пробные занятия и переход к оплате"),
    "calendar": ("Календарь", "Напоминания и задачи команды"),
    "search": ("Поиск", "Спортсмены, заявки, группы и контакты"),
}


def role_required(min_rank):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if {Role.MANAGER: 0, Role.SENIOR: 1, Role.BOSS: 2}[user_role(request.user)] < min_rank:
                return HttpResponseForbidden("Недостаточно прав")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def page_context(request, page, **extra):
    title, subtitle = PAGE_META[page]
    context = {
        "page": page,
        "title": title,
        "subtitle": subtitle,
        "current_role": user_role(request.user),
        "is_boss": user_role(request.user) == Role.BOSS,
        "is_senior": user_role(request.user) in (Role.SENIOR, Role.BOSS),
    }
    context.update(extra)
    return context


def log_action(request, action, obj, description):
    AuditEvent.objects.create(
        actor=request.user,
        action=action,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj and obj.pk else "",
        description=description,
    )


def login_page(request):
    if request.user.is_authenticated:
        return redirect("attendance")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user and user.is_active:
            login(request, user)
            return redirect(request.GET.get("next") or "attendance")
        messages.error(request, "Неверный логин или пароль")
    return render(request, "crm/login.html")


@login_required
def logout_page(request):
    logout(request)
    return redirect("login")


@login_required
def attendance_page(request):
    groups = Group.objects.filter(is_active=True).select_related("trainer")
    selected_group = groups.filter(pk=request.GET.get("group")).first() or groups.first()
    start_raw = request.GET.get("week")
    try:
        chosen = date.fromisoformat(start_raw) if start_raw else timezone.localdate()
    except ValueError:
        chosen = timezone.localdate()
    week_start = chosen - timedelta(days=chosen.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark":
            child = get_object_or_404(Child, pk=request.POST.get("child_id"))
            mark_date = date.fromisoformat(request.POST["date"])
            status = request.POST.get("status", "")
            if status:
                charge = Decimal("0")
                if status == Attendance.Status.PRESENT and not child.active_subscription() and child.group:
                    charge = child.group.single_session_price
                attendance, _ = Attendance.objects.update_or_create(
                    child=child, date=mark_date, slot=None,
                    defaults={"status": status, "charge_amount": charge},
                )
                log_action(request, "attendance.update", attendance, f"Изменена отметка: {child} — {mark_date:%d.%m.%Y}")
            else:
                Attendance.objects.filter(child=child, date=mark_date, slot=None).delete()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True})
            return redirect(f"{reverse('attendance')}?group={child.group_id}&week={week_start.isoformat()}")
        if action == "create_child":
            full_name = request.POST.get("full_name", "").split()
            if len(full_name) < 2:
                messages.error(request, "Укажите фамилию и имя ребёнка")
            else:
                child = Child.objects.create(
                    last_name=full_name[0],
                    first_name=full_name[1],
                    patronymic=" ".join(full_name[2:]),
                    birth_year=int(request.POST.get("birth_year") or timezone.localdate().year - 7),
                    parent_phone=request.POST.get("parent_phone", ""),
                    parent_name=request.POST.get("parent_name", ""),
                    group_id=request.POST.get("group_id") or None,
                    status=Child.Status.TRIAL if request.POST.get("trial") else Child.Status.ACTIVE,
                    trial_from=timezone.localdate() if request.POST.get("trial") else None,
                )
                log_action(request, "child.create", child, f"Добавлен спортсмен {child}")
                messages.success(request, "Спортсмен добавлен")
            return redirect("attendance")

    children = []
    if selected_group:
        queryset = selected_group.children.filter(status__in=[Child.Status.ACTIVE, Child.Status.TRIAL])
        search = request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(Q(last_name__icontains=search) | Q(first_name__icontains=search) | Q(parent_phone__icontains=search))
        marks = Attendance.objects.filter(child__in=queryset, date__range=(week_dates[0], week_dates[-1]))
        mark_map = {(m.child_id, m.date): m.status for m in marks}
        style_map = {
            Attendance.Status.PRESENT: ("+", "bg-emerald-100 text-emerald-700"),
            Attendance.Status.ABSENT: ("×", "bg-red-100 text-red-700"),
            Attendance.Status.EXCUSED: ("У", "bg-purple-100 text-purple-700"),
            Attendance.Status.FROZEN: ("❄", "bg-blue-100 text-blue-700"),
            Attendance.Status.VACATION: ("О", "bg-amber-100 text-amber-700"),
        }
        for child in queryset:
            sub = child.active_subscription()
            child_marks = []
            for day in week_dates:
                status = mark_map.get((child.pk, day), "")
                symbol, css = style_map.get(status, ("", "bg-slate-100 text-slate-400"))
                child_marks.append({"date": day, "status": status, "symbol": symbol, "css": css})
            children.append({
                "child": child,
                "form": ChildForm(instance=child, prefix=f"child-{child.pk}"),
                "subscription": sub,
                "left": child.sessions_left(),
                "debt": child.debt(),
                "expiry": child.nearest_expiry(),
                "marks": child_marks,
                "attendance_history": child.attendances.all()[:8],
                "competition_history": child.competition_entries.select_related("competition")[:8],
            })
        if request.GET.get("sort") == "remaining":
            children.sort(key=lambda item: item["left"])
    return render(request, "crm/attendance.html", page_context(
        request, "attendance", groups=groups, selected_group=selected_group,
        week_dates=week_dates, week_start=week_start, prev_week=week_start-timedelta(days=7),
        next_week=week_start+timedelta(days=7), children=children, today=timezone.localdate(),
    ))


@login_required
def child_edit(request, pk):
    child = get_object_or_404(Child, pk=pk)
    next_url = request.POST.get("next") or reverse("attendance")
    if request.method != "POST":
        return redirect(next_url)
    action = request.POST.get("action", "save")
    if action == "archive":
        child.status = Child.Status.ARCHIVED
        child.save(update_fields=["status"])
        log_action(request, "child.archive", child, f"{child} перемещён в архив")
        messages.success(request, "Спортсмен перемещён в архив")
        return redirect(next_url)
    form = ChildForm(request.POST, request.FILES, instance=child, prefix=f"child-{child.pk}")
    if form.is_valid():
        child = form.save()
        if child.status != Child.Status.TRIAL:
            child.trial_from = None
            child.save(update_fields=["trial_from"])
        log_action(request, "child.update", child, f"Обновлена карточка спортсмена {child}")
        messages.success(request, "Карточка спортсмена обновлена")
    else:
        messages.error(request, "Не удалось сохранить карточку: " + "; ".join(f"{field}: {', '.join(errors)}" for field, errors in form.errors.items()))
    return redirect(next_url)


@login_required
def statistics_page(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    active = Child.objects.filter(status=Child.Status.ACTIVE)
    total = Child.objects.exclude(status=Child.Status.ARCHIVED).count()
    new = Child.objects.filter(created_at__date__gte=month_start).count()
    lost = Child.objects.filter(status=Child.Status.LOST).count()
    revenue = Payment.objects.filter(date__gte=month_start).aggregate(value=Sum("amount"))["value"] or 0
    group_stats = Group.objects.filter(is_active=True).annotate(
        children_count=Count("children", filter=Q(children__status=Child.Status.ACTIVE), distinct=True),
        attended=Count("children__attendances", filter=Q(children__attendances__status=Attendance.Status.PRESENT, children__attendances__date__gte=month_start)),
        marked=Count("children__attendances", filter=Q(children__attendances__status__in=[Attendance.Status.PRESENT, Attendance.Status.ABSENT], children__attendances__date__gte=month_start)),
    )
    for group in group_stats:
        group.attendance_percent = round(group.attended * 100 / group.marked) if group.marked else 0
    return render(request, "crm/statistics.html", page_context(
        request, "statistics", total=total, active_count=active.count(), new_count=new,
        lost_count=lost, revenue=revenue, group_stats=group_stats,
    ))


@login_required
def payments_page(request):
    editing_tariff = Tariff.objects.filter(pk=request.GET.get("edit_tariff")).first()
    editing_subscription = Subscription.objects.filter(pk=request.GET.get("edit_subscription")).first()
    tariff_form = TariffForm(request.POST or None, prefix="tariff", instance=editing_tariff)
    subscription_form = SubscriptionForm(
        request.POST or None, prefix="subscription", instance=editing_subscription,
        initial={"start_date": timezone.localdate()},
    )
    if request.method == "POST":
        action = request.POST.get("action", "payment")
        if action == "payment":
            child = get_object_or_404(Child, pk=request.POST.get("child_id"))
            try:
                amount = Decimal(request.POST.get("amount", "0"))
            except InvalidOperation:
                amount = Decimal("0")
            if amount <= 0:
                messages.error(request, "Сумма должна быть больше нуля")
            else:
                payment = Payment.objects.create(
                    child=child,
                    subscription=child.active_subscription(),
                    amount=amount,
                    date=request.POST.get("date") or timezone.localdate(),
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
                    subscriptions=Subscription.objects.select_related("child", "tariff"), children=Child.objects.filter(status=Child.Status.ACTIVE),
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
                Subscription.objects.filter(
                    child=subscription.child, is_active=True,
                ).exclude(pk=subscription.pk).update(is_active=False)
                if subscription.child.status == Child.Status.TRIAL:
                    subscription.child.status = Child.Status.ACTIVE
                    subscription.child.trial_from = None
                    subscription.child.save(update_fields=["status", "trial_from"])
                log_action(request, "subscription.save", subscription, f"Сохранён абонемент {subscription}")
                messages.success(request, "Абонемент назначен")
            else:
                messages.error(request, "Проверьте данные абонемента")
                return redirect("payments")
        elif action == "cancel_subscription":
            subscription = get_object_or_404(Subscription, pk=request.POST.get("subscription_id"))
            subscription.is_active = False
            subscription.save(update_fields=["is_active"])
            log_action(request, "subscription.cancel", subscription, f"Отменён абонемент {subscription}")
            messages.success(request, "Абонемент отменён без удаления истории")
        return redirect("payments")
    today = timezone.localdate()
    limit = today + timedelta(days=14)
    renewals = []
    for child in Child.objects.filter(status=Child.Status.ACTIVE).select_related("group"):
        sub = child.active_subscription()
        if sub and sub.end_date <= limit:
            renewals.append({"child": child, "subscription": sub, "debt": child.debt(), "days": (sub.end_date-today).days})
    renewals.sort(key=lambda item: item["subscription"].end_date)
    return render(request, "crm/payments.html", page_context(
        request, "payments", renewals=renewals, children=Child.objects.filter(status=Child.Status.ACTIVE),
        urgent_count=sum(1 for x in renewals if x["days"] <= 3), expected=sum((x["subscription"].price for x in renewals), Decimal("0")),
        tariffs=Tariff.objects.all(), subscriptions=Subscription.objects.select_related("child", "tariff")[:100],
        tariff_form=tariff_form, subscription_form=subscription_form,
        editing_tariff=editing_tariff, editing_subscription=editing_subscription,
    ))


@login_required
def expenses_page(request):
    editing = Expense.objects.filter(pk=request.GET.get("edit")).first()
    form = ExpenseForm(request.POST or None, request.FILES or None, instance=editing)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            expense = get_object_or_404(Expense, pk=request.POST.get("expense_id"))
            log_action(request, "expense.delete", expense, f"Удалён расход {expense.title} на {expense.amount} ₽")
            expense.delete()
            messages.success(request, "Расход удалён")
            return redirect("expenses")
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user
            expense.save()
            log_action(request, "expense.save", expense, f"Сохранён расход {expense.title} на {expense.amount} ₽")
            messages.success(request, "Расход сохранён")
            return redirect("expenses")
        messages.error(request, "Проверьте заполнение формы")
    today = timezone.localdate()
    month_start = today.replace(day=1)
    expenses = Expense.objects.select_related("created_by")
    month_expenses = expenses.filter(date__gte=month_start)
    total = month_expenses.aggregate(value=Sum("amount"))["value"] or 0
    household = month_expenses.filter(category=Expense.Category.HOUSEHOLD).aggregate(value=Sum("amount"))["value"] or 0
    return render(request, "crm/expenses.html", page_context(
        request, "expenses", form=form, expenses=expenses, editing=editing,
        total=total, household=household, operations=month_expenses.count(),
    ))


def recalculate_places(competition):
    for category in competition.entries.values_list("category", flat=True).distinct():
        entries = list(competition.entries.filter(category=category))
        entries.sort(key=lambda entry: entry.total_points(), reverse=True)
        last_total = None
        last_place = 0
        for index, entry in enumerate(entries, 1):
            total = entry.total_points()
            place = last_place if total == last_total else index
            CompetitionEntry.objects.filter(pk=entry.pk).update(place=place)
            last_total, last_place = total, place


@login_required
def competitions_page(request):
    competitions = Competition.objects.all()
    selected = competitions.filter(pk=request.GET.get("competition")).first() or competitions.first()
    editing_competition = competitions.filter(pk=request.GET.get("edit_competition")).first()
    editing_apparatus = Apparatus.objects.filter(pk=request.GET.get("edit_apparatus"), competition=selected).first() if selected else None
    competition_form = CompetitionForm(prefix="competition", instance=editing_competition)
    entry_form = CompetitionEntryForm(prefix="entry")
    apparatus_form = ApparatusForm(prefix="apparatus", instance=editing_apparatus)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_competition":
            target_competition = competitions.filter(pk=request.POST.get("competition_id")).first()
            competition_form = CompetitionForm(request.POST, prefix="competition", instance=target_competition)
            if competition_form.is_valid():
                selected = competition_form.save()
                if not target_competition:
                    for order, name in enumerate(("Прыжок", "Брусья", "Бревно", "Вольные")):
                        Apparatus.objects.create(competition=selected, name=name, order=order)
                log_action(request, "competition.save", selected, f"Сохранено соревнование {selected.name}")
                messages.success(request, "Соревнование сохранено")
                return redirect(f"{reverse('competitions')}?competition={selected.pk}")
        elif action == "save_apparatus" and selected:
            target_apparatus = selected.apparatus.filter(pk=request.POST.get("apparatus_id")).first()
            apparatus_form = ApparatusForm(request.POST, prefix="apparatus", instance=target_apparatus)
            if apparatus_form.is_valid():
                apparatus_item = apparatus_form.save(commit=False)
                apparatus_item.competition = selected
                apparatus_item.save()
                for entry in selected.entries.all():
                    ApparatusScore.objects.get_or_create(entry=entry, apparatus=apparatus_item, defaults={"points": 0})
                log_action(request, "competition.apparatus", apparatus_item, f"Сохранена дисциплина {apparatus_item.name}")
                messages.success(request, "Дисциплина сохранена")
                return redirect(f"{reverse('competitions')}?competition={selected.pk}")
        elif action == "delete_apparatus" and selected:
            apparatus_item = get_object_or_404(selected.apparatus, pk=request.POST.get("apparatus_id"))
            description = apparatus_item.name
            apparatus_item.delete()
            log_action(request, "competition.apparatus.delete", selected, f"Удалена дисциплина {description}")
            messages.success(request, "Дисциплина и её баллы удалены")
            return redirect(f"{reverse('competitions')}?competition={selected.pk}")
        elif action == "add_entry" and selected:
            entry_form = CompetitionEntryForm(request.POST, prefix="entry")
            if entry_form.is_valid():
                entry = entry_form.save(commit=False)
                entry.competition = selected
                entry.save()
                for apparatus in selected.apparatus.all():
                    ApparatusScore.objects.create(entry=entry, apparatus=apparatus, points=0)
                log_action(request, "competition.entry", entry, f"Добавлен участник {entry.child} в {selected.name}")
                messages.success(request, "Участник добавлен")
                return redirect(f"{reverse('competitions')}?competition={selected.pk}")
        elif action == "save_scores" and selected:
            for entry in selected.entries.all():
                for apparatus in selected.apparatus.all():
                    key = f"score_{entry.pk}_{apparatus.pk}"
                    try:
                        points = Decimal(request.POST.get(key, "0").replace(",", "."))
                    except InvalidOperation:
                        points = Decimal("0")
                    ApparatusScore.objects.update_or_create(entry=entry, apparatus=apparatus, defaults={"points": points})
            recalculate_places(selected)
            log_action(request, "competition.scores", selected, f"Обновлены результаты {selected.name}")
            messages.success(request, "Баллы сохранены, места пересчитаны")
            return redirect(f"{reverse('competitions')}?competition={selected.pk}")
        messages.error(request, "Проверьте заполнение формы")
    entry_rows = []
    apparatus = list(selected.apparatus.all()) if selected else []
    if selected:
        for entry in selected.entries.select_related("child").prefetch_related("scores"):
            score_map = {score.apparatus_id: score for score in entry.scores.all()}
            entry_rows.append({
                "entry": entry,
                "scores": [
                    {"apparatus_id": item.pk, "points": score_map[item.pk].points if item.pk in score_map else Decimal("0")}
                    for item in apparatus
                ],
                "total": entry.total_points(),
            })
    return render(request, "crm/competitions.html", page_context(
        request, "competitions", competitions=competitions, selected=selected,
        apparatus=apparatus, entry_rows=entry_rows, competition_form=competition_form,
        entry_form=entry_form, apparatus_form=apparatus_form,
        editing_competition=editing_competition, editing_apparatus=editing_apparatus,
    ))


@login_required
def competition_export(request, pk):
    competition = get_object_or_404(Competition, pk=pk)
    apparatus = list(competition.apparatus.all())
    wb = Workbook()
    ws = wb.active
    ws.title = "Результаты"
    headers = ["Спортсмен", "Год рождения", "Разряд", "Категория", *[a.name for a in apparatus], "Итого", "Место"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17202A")
        cell.alignment = Alignment(horizontal="center")
    for entry in competition.entries.select_related("child").prefetch_related("scores"):
        score_map = {score.apparatus_id: score.points for score in entry.scores.all()}
        ws.append([str(entry.child), entry.child.birth_year, entry.rank, entry.category, *[float(score_map.get(a.pk, 0)) for a in apparatus], float(entry.total_points()), entry.place or ""])
    widths = [28, 14, 14, 18, *([12] * len(apparatus)), 12, 10]
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + index)].width = width
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="competition-{competition.pk}.xlsx"'
    wb.save(response)
    log_action(request, "competition.export", competition, f"Выгружены результаты {competition.name}")
    return response


@login_required
def notifications_page(request):
    if request.method == "POST":
        task = get_object_or_404(ManagerTask, pk=request.POST.get("task_id"))
        if task.assignee_id not in (None, request.user.pk) and user_role(request.user) != Role.BOSS:
            return HttpResponseForbidden("Это задача другого пользователя")
        task.is_done = not task.is_done
        task.done_at = timezone.now() if task.is_done else None
        task.save(update_fields=["is_done", "done_at"])
        log_action(request, "task.toggle", task, f"Задача «{task.title}»: {'выполнена' if task.is_done else 'возвращена'}")
        messages.success(request, "Статус задачи изменён")
        return redirect("notifications")
    tasks = ManagerTask.objects.select_related("assignee", "created_by")
    if user_role(request.user) != Role.BOSS:
        tasks = tasks.filter(Q(assignee=request.user) | Q(assignee__isnull=True))
    today = timezone.localdate()
    alerts = []
    for child in Child.objects.filter(status=Child.Status.ACTIVE):
        expiry = child.nearest_expiry()
        debt = child.debt()
        if expiry and expiry <= today + timedelta(days=7):
            alerts.append({"kind": "subscription", "child": child, "expiry": expiry, "debt": debt})
    trials = Child.objects.filter(status=Child.Status.TRIAL, trial_from__lte=today)
    reminders = Reminder.objects.filter(
        Q(assignee=request.user) | Q(visible_to_all=True),
        is_done=False,
        remind_at__date__lte=today + timedelta(days=1),
    ).select_related("assignee")
    imported_leads = Lead.objects.filter(imported_from_ad=True, status=Lead.Status.NEW)
    return render(request, "crm/notifications.html", page_context(
        request, "notifications", tasks=tasks, alerts=alerts, trials=trials,
        reminders=reminders, imported_leads=imported_leads,
        open_count=tasks.filter(is_done=False).count() + len(alerts) + trials.count() + reminders.count() + imported_leads.count(), today=today,
    ))


@login_required
def applications_page(request):
    editing = Lead.objects.filter(pk=request.GET.get("edit")).first()
    form = LeadForm(request.POST or None, instance=editing)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "import_raw":
            raw = request.POST.get("raw_application", "")
            parsed = {}
            aliases = {"имя": "full_name", "фио": "full_name", "телефон": "phone", "возраст": "age_text", "источник": "source", "кампания": "source", "комментарий": "comment"}
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                target = aliases.get(key.strip().lower())
                if target and value.strip():
                    parsed[target] = value.strip()
            if parsed.get("full_name"):
                parsed.setdefault("source", "VK Реклама")
                lead = Lead.objects.create(imported_from_ad=True, **parsed)
                log_action(request, "lead.import", lead, f"Импортирована рекламная заявка {lead.full_name}")
                messages.success(request, "Заявка распознана и выделена как рекламная")
            else:
                messages.error(request, "Не удалось распознать имя. Используйте строку «Имя: ...»")
            return redirect("applications")
        if action == "create_newcomer":
            lead = get_object_or_404(Lead, pk=request.POST.get("lead_id"))
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
            lead.status = Lead.Status.QUALIFIED
            lead.save(update_fields=["status"])
            log_action(request, "lead.newcomer", newcomer, f"Из заявки создан новичок {newcomer.full_name}")
            messages.success(request, "Новичок создан и предзаполнен из заявки")
            return redirect("newcomers")
        if form.is_valid():
            lead = form.save()
            log_action(request, "lead.save", lead, f"Сохранена заявка {lead.full_name}")
            messages.success(request, "Заявка сохранена")
            return redirect("applications")
        messages.error(request, "Проверьте данные заявки")
    leads = Lead.objects.select_related("trainer", "group").prefetch_related("newcomers")
    return render(request, "crm/applications.html", page_context(
        request, "applications", leads=leads, form=form, editing=editing,
        imported_count=leads.filter(imported_from_ad=True, status=Lead.Status.NEW).count(),
    ))


@login_required
def newcomers_page(request):
    editing = Newcomer.objects.filter(pk=request.GET.get("edit")).first()
    form = NewcomerForm(request.POST or None, instance=editing)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "convert":
            newcomer = get_object_or_404(Newcomer, pk=request.POST.get("newcomer_id"))
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
                status=Child.Status.ACTIVE if newcomer.paid else Child.Status.TRIAL,
                trial_from=None if newcomer.paid else timezone.localdate(),
                note=newcomer.comment,
            )
            newcomer.child = child
            newcomer.save(update_fields=["child"])
            if newcomer.lead:
                newcomer.lead.child = child
                newcomer.lead.save(update_fields=["child"])
            log_action(request, "newcomer.convert", child, f"Новичок {newcomer.full_name} перенесён в спортсмены")
            messages.success(request, "Карточка спортсмена создана")
            return redirect("payments" if newcomer.paid else "attendance")
        if form.is_valid():
            newcomer = form.save()
            log_action(request, "newcomer.save", newcomer, f"Сохранён новичок {newcomer.full_name}")
            messages.success(request, "Новичок сохранён")
            return redirect("newcomers")
        messages.error(request, "Проверьте данные новичка")
    return render(request, "crm/newcomers.html", page_context(
        request, "newcomers", newcomers=Newcomer.objects.select_related("lead", "trainer", "group", "child"),
        form=form, editing=editing,
    ))


@login_required
def calendar_page(request):
    editing = Reminder.objects.filter(pk=request.GET.get("edit")).first()
    if editing and editing.created_by_id != request.user.pk and user_role(request.user) != Role.BOSS:
        return HttpResponseForbidden("Редактировать чужое напоминание может только начальник")
    form = ReminderForm(request.POST or None, instance=editing, initial={"assignee": request.user})
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "set_shift":
            profile, _ = StaffProfile.objects.get_or_create(user=request.user)
            try:
                profile.shift_anchor = date.fromisoformat(request.POST.get("shift_anchor", ""))
                profile.save(update_fields=["shift_anchor"])
                messages.success(request, "График 2/2 пересчитан")
            except ValueError:
                messages.error(request, "Укажите первый рабочий день")
            return redirect("calendar")
        if action == "toggle":
            reminder = get_object_or_404(Reminder, pk=request.POST.get("reminder_id"))
            if reminder.assignee_id != request.user.pk and user_role(request.user) != Role.BOSS:
                return HttpResponseForbidden("Недостаточно прав")
            reminder.is_done = not reminder.is_done
            reminder.save(update_fields=["is_done"])
            return redirect("calendar")
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.created_by = editing.created_by if editing else request.user
            reminder.save()
            log_action(request, "reminder.save", reminder, f"Сохранено напоминание {reminder.title}")
            messages.success(request, "Напоминание сохранено")
            return redirect("calendar")
        messages.error(request, "Проверьте дату и поля напоминания")
    visible = Reminder.objects.select_related("assignee", "created_by").filter(
        Q(assignee=request.user) | Q(created_by=request.user) | Q(visible_to_all=True)
    ).distinct()
    if user_role(request.user) == Role.BOSS:
        visible = Reminder.objects.select_related("assignee", "created_by")
    week_start = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
    days = []
    for offset in range(14):
        day = week_start + timedelta(days=offset)
        day_items = [item for item in visible if timezone.localtime(item.remind_at).date() == day]
        days.append({"date": day, "items": day_items})
    shift_rows = []
    for profile in StaffProfile.objects.select_related("user", "branch").filter(user__is_active=True).exclude(role=Role.BOSS):
        work_days = set()
        if profile.shift_anchor:
            for item in days:
                if (item["date"] - profile.shift_anchor).days % 4 in (0, 1):
                    work_days.add(item["date"])
        shift_rows.append({"profile": profile, "work_days": work_days})
    return render(request, "crm/calendar.html", page_context(
        request, "calendar", form=form, editing=editing, days=days, reminders=visible,
        today=timezone.localdate(), shift_rows=shift_rows,
    ))


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
    month = today.replace(day=1)
    target = RevenueTarget.objects.filter(month=month).first()
    task_form = ManagerTaskForm(prefix="task")
    target_form = RevenueTargetForm(prefix="target", instance=target, initial={"month": month})
    if request.method == "POST":
        if request.POST.get("action") == "create_task":
            task_form = ManagerTaskForm(request.POST, prefix="task")
            if task_form.is_valid():
                task = task_form.save(commit=False)
                task.created_by = request.user
                task.save()
                log_action(request, "task.create", task, f"Поставлена задача «{task.title}»")
                messages.success(request, "Задача поставлена")
                return redirect("boss")
        elif request.POST.get("action") == "set_target":
            target_form = RevenueTargetForm(request.POST, prefix="target", instance=target)
            if target_form.is_valid():
                target = target_form.save(commit=False)
                target.set_by = request.user
                target.save()
                log_action(request, "revenue_target.save", target, f"Цель выручки: {target.amount} ₽")
                messages.success(request, "Цель обновлена")
                return redirect("boss")
        messages.error(request, "Проверьте заполнение формы")
    revenue = Payment.objects.filter(date__gte=month).aggregate(value=Sum("amount"))["value"] or 0
    target_amount = target.amount if target else Decimal("0")
    target_percent = min(100, round(revenue * 100 / target_amount)) if target_amount else 0
    salaries = SalaryPayout.objects.filter(month=month).aggregate(value=Sum("amount"))["value"] or 0
    trainer_rows = []
    for trainer in Trainer.objects.filter(is_active=True):
        children = Child.objects.filter(group__trainer=trainer, status=Child.Status.ACTIVE)
        marked = Attendance.objects.filter(child__in=children, date__gte=month, status__in=[Attendance.Status.PRESENT, Attendance.Status.ABSENT]).count()
        present = Attendance.objects.filter(child__in=children, date__gte=month, status=Attendance.Status.PRESENT).count()
        trial = Child.objects.filter(group__trainer=trainer, status=Child.Status.TRIAL).count()
        lost = Child.objects.filter(group__trainer=trainer, status=Child.Status.LOST).count()
        trainer_rows.append({"trainer": trainer, "children": children.count(), "trial": trial, "lost": lost, "attendance": round(present*100/marked) if marked else 0})
    trainer_rows.sort(key=lambda row: row["attendance"], reverse=True)
    all_logs = request.GET.get("all_logs") == "1"
    events = AuditEvent.objects.select_related("actor")
    if not all_logs:
        events = events[:12]
    return render(request, "crm/boss.html", page_context(
        request, "boss", revenue=revenue, target=target, target_amount=target_amount,
        target_percent=target_percent, salaries=salaries, active_count=Child.objects.filter(status=Child.Status.ACTIVE).count(),
        trainer_rows=trainer_rows, events=events, all_logs=all_logs,
        overdue_tasks=ManagerTask.objects.filter(is_done=False, due_date__lt=today).count(),
        task_form=task_form, target_form=target_form,
    ))


@role_required(1)
def users_page(request):
    form = StaffCreateForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create" and form.is_valid():
            if form.cleaned_data["role"] == Role.BOSS and user_role(request.user) != Role.BOSS:
                form.add_error("role", "Только начальник может создать аккаунт начальника")
            else:
                user = form.save()
                log_action(request, "user.create", user, f"Создан пользователь {user.username}")
                messages.success(request, "Пользователь создан")
                return redirect("users")
        if action == "toggle":
            user = get_object_or_404(get_user_model(), pk=request.POST.get("user_id"))
            if user == request.user:
                messages.error(request, "Нельзя отключить собственный аккаунт")
            elif user_role(user) == Role.BOSS and user_role(request.user) != Role.BOSS:
                return HttpResponseForbidden("Только начальник управляет аккаунтом начальника")
            else:
                user.is_active = not user.is_active
                user.save(update_fields=["is_active"])
                log_action(request, "user.toggle", user, f"Аккаунт {user.username}: {'включён' if user.is_active else 'отключён'}")
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
