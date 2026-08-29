from django.shortcuts import render


PAGES = {
    "attendance": ("Табель", "Отмечайте посещения прямо в таблице"),
    "statistics": ("Статистика", "Главные показатели клуба за август"),
    "payments": ("Продления", "Кому пора напомнить об оплате"),
    "expenses": ("Расходы", "Бытовые закупки и другие расходы"),
    "competitions": ("Соревнования", "Баллы, места и история выступлений"),
    "notifications": ("Уведомления", "Задачи и события, требующие внимания"),
    "boss": ("Для руководителя", "Выручка, KPI и работа команды"),
    "users": ("Пользователи", "Доступы сотрудников и роли"),
    "profile": ("Мой профиль", "Личные данные и безопасность"),
}


def app_page(request, page="attendance"):
    if page not in PAGES:
        page = "attendance"
    title, subtitle = PAGES[page]
    return render(request, f"crm/{page}.html", {
        "page": page, "title": title, "subtitle": subtitle,
    })


def login_page(request):
    return render(request, "crm/login.html")


from datetime import datetime, timedelta
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Child, Group, ScheduleSlot, Attendance

@login_required
def attendance_view(request):
    # Получаем параметры
    group_id = request.GET.get('group_id')
    week_start_str = request.GET.get('week_start')  # формат YYYY-MM-DD (понедельник)

    # Определяем группу
    if group_id:
        group = get_object_or_404(Group, id=group_id, is_active=True)
    else:
        group = Group.objects.filter(is_active=True).first()
        if not group:
            # Если нет групп — пустая таблица
            return render(request, 'crm/attendance.html', {
                'groups': Group.objects.all(),
                'selected_group': None,
                'days': [],
                'children_data': [],
                'week_start': None,
            })

    # Определяем начало недели
    if week_start_str:
        try:
            week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        except ValueError:
            week_start = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
    else:
        week_start = timezone.localdate() - timedelta(days=timezone.localdate().weekday())

    # Получаем дни недели, по которым есть занятия у группы
    slots = ScheduleSlot.objects.filter(group=group).order_by('weekday', 'start_time')
    # Уникальные дни недели (0-6)
    weekdays = sorted(set(slot.weekday for slot in slots))

    # Строим список дат для этих дней недели (от week_start)
    days = []
    for wd in weekdays:
        days.append(week_start + timedelta(days=wd))

    # Выбираем детей группы
    children = Child.objects.filter(group=group).select_related('group__trainer').prefetch_related(
        'subscriptions', 'payments', 'attendances', 'ranks'
    ).order_by('last_name', 'first_name')

    # Для каждого ребёнка собираем данные
    children_data = []
    today = timezone.localdate()
    for child in children:
        # Остаток занятий (используем метод модели)
        sessions_left = child.sessions_left()
        sessions_total = 0
        active_sub = child.active_subscription()
        subscription_end_soon = False
        if active_sub:
            subscription_end_soon = (active_sub.end_date <= today + timedelta(days=3)) and (active_sub.end_date >= today)
        if active_sub:
            sessions_total = active_sub.sessions_total

        debt = child.debt()

        # Инициалы
        initials = f"{child.last_name[0]}{child.first_name[0]}".upper()

        # Разряд (последний)
        latest_rank = child.ranks.order_by('-year').first()
        rank_str = latest_rank.rank if latest_rank else 'б/р'

        # Отметки на выбранные даты
        attendance_map = {}
        for att in child.attendances.filter(date__in=days):
            attendance_map[att.date] = att.status

        # Формируем список записей для шаблона
        attendance_entries = []
        for day in days:
            attendance_entries.append({
                'date': day,
                'status': attendance_map.get(day, '')
            })

        children_data.append({
            'child': child,
            'initials': initials,
            'birth_year': child.birth_year,
            'rank': rank_str,
            'sessions_left': sessions_left,
            'sessions_total': sessions_total,
            'debt': debt,
            'subscription_end': active_sub.end_date if active_sub else None,
            'status': child.status,
            'attendance_entries': attendance_entries,
            'subscription_end_soon': subscription_end_soon,
        })

    context = {
        'groups': Group.objects.filter(is_active=True),
        'selected_group': group,
        'days': days,
        'week_start': week_start,
        'week_start_prev': (week_start - timedelta(days=7)).strftime('%Y-%m-%d'),
        'week_start_next': (week_start + timedelta(days=7)).strftime('%Y-%m-%d'),
        'children_data': children_data,
        'today': today,
    }
    return render(request, 'crm/attendance.html', context)


@require_POST
@login_required
def update_attendance(request):
    child_id = request.POST.get('child_id')
    date_str = request.POST.get('date')
    status = request.POST.get('status')

    if not child_id or not date_str or status is None:
        return JsonResponse({'success': False, 'error': 'Missing parameters'}, status=400)

    try:
        child = Child.objects.get(id=child_id)
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (Child.DoesNotExist, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid child or date'}, status=400)

    # Валидные статусы (можно сверить с моделью)
    valid_statuses = [s[0] for s in Attendance.Status.choices]
    if status not in valid_statuses:
        return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)

    # Ищем существующую отметку
    attendance, created = Attendance.objects.get_or_create(
        child=child,
        date=date,
        defaults={'status': status}
    )
    if not created:
        attendance.status = status
        attendance.save()

    return JsonResponse({'success': True, 'status': attendance.status})