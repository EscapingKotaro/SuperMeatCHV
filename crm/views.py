from django.shortcuts import render


PAGES = {
    "statistics": ("Статистика", "Главные показатели клуба за август"),
    "payments": ("Продления", "Кому пора напомнить об оплате"),
    "expenses": ("Расходы", "Бытовые закупки и другие расходы"),
    "competitions": ("Соревнования", "Баллы, места и история выступлений"),
    "notifications": ("Уведомления", "Задачи и события, требующие внимания"),
    "boss": ("Для руководителя", "Выручка, KPI и работа команды"),
    "users": ("Пользователи", "Доступы сотрудников и роли"),
    "profile": ("Мой профиль", "Личные данные и безопасность"),
}


def app_page(request, page="statistics"):
    title, subtitle = PAGES[page]
    return render(request, f"crm/{page}.html", {
        "page": page, "title": title, "subtitle": subtitle,
    })

from django.contrib.auth import logout
from django.shortcuts import redirect

def logout_view(request):
    logout(request)
    return redirect('login')


from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse


def login_page(request):
    # Если пользователь уже авторизован — сразу отправляем на главную
    if request.user.is_authenticated:
        return redirect('attendance')  # замени на имя своего URL

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me') == 'on'

        # Проверяем, что поля не пустые
        if not username or not password:
            messages.error(request, 'Введите логин и пароль')
            return render(request, 'crm/login.html')

        # Аутентификация
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Если "Запомнить меня" — сессия живёт 2 недели, иначе до закрытия браузера
            if remember_me:
                request.session.set_expiry(1209600)  # 2 недели в секундах
            else:
                request.session.set_expiry(0)  # при закрытии браузера

            # Редирект на нужную страницу (например, attendance)
            return redirect('attendance')  # замени на имя URL
        else:
            messages.error(request, 'Неверный логин или пароль')

    return render(request, 'crm/login.html')


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
    week_start_str = request.GET.get('week_start')  # формат YYYY-MM-DD (понедельник первой недели)

    # Определяем группу
    if group_id:
        group = get_object_or_404(Group, id=group_id)
    else:
        group = Group.objects.filter(is_active=True).first() or Group.objects.first()
        if not group:
            # Если групп вообще нет
            return render(request, 'crm/attendance.html', {
                'groups': Group.objects.none(),
                'selected_group': None,
                'days': [],
                'week_data': [],
                'children_data': [],
                'week_start': None,
            })

    # Определяем начало первой недели (по умолчанию – понедельник текущей недели)
    if week_start_str:
        try:
            week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        except ValueError:
            week_start = timezone.localdate() - timedelta(days=5)
    else:
        # Начало окна = сегодня - 5 дней
        week_start = timezone.localdate() - timedelta(days=5)
    # Получаем все слоты расписания группы (дни недели и время)
    period_end = week_start + timedelta(days=13)
    slots = ScheduleSlot.objects.filter(group=group).order_by('weekday', 'start_time')
    if not slots.exists():
        # Если расписания нет, дни будут пустыми
        days = []
        week_data = []
    else:
        # Строим список дат на две недели (текущая + следующая)
        days = []
        week_data = []  # Список словарей: {date, week_number, weekday, start_time}
        for week_offset in (0, 7):  # 0 – текущая неделя, 7 – следующая
            for slot in slots:
                day_date = week_start + timedelta(days=slot.weekday + week_offset)
                # Защита от дублей, если несколько слотов в один день
                if day_date not in [d['date'] for d in week_data]:
                    week_data.append({
                        'date': day_date,
                        'week_number': 1 if week_offset == 0 else 2,
                        'weekday': slot.weekday,
                        'start_time': slot.start_time,
                    })
                else:
                    # Обновляем время, если уже есть дата (возьмём самое раннее)
                    for d in week_data:
                        if d['date'] == day_date:
                            d['start_time'] = min(d['start_time'], slot.start_time)
                            break
        # Сортируем по дате и времени
        week_data.sort(key=lambda x: (x['date'], x['start_time']))
        days = [d['date'] for d in week_data]

    # Выбираем детей группы
    children = Child.objects.filter(group=group).select_related('group__trainer').prefetch_related(
        'subscriptions', 'payments', 'attendances', 'ranks'
    ).order_by('last_name', 'first_name')

    # Для каждого ребёнка собираем данные
    children_data = []
    today = timezone.localdate()
    for child in children:
        sessions_left = child.sessions_left()
        sessions_total = 0
        active_sub = child.active_subscription()
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
        for entry in week_data:
            day = entry['date']
            attendance_entries.append({
                'date': day,
                'week_number': entry['week_number'],
                'status': attendance_map.get(day, '')
            })

        # Проверка, скоро ли окончание абонемента
        subscription_end_soon = False
        if active_sub:
            subscription_end_soon = (active_sub.end_date <= today + timedelta(days=3)) and (active_sub.end_date >= today)
        subscription_end_index = None
        if active_sub and attendance_entries:
            # Если абонемент заканчивается внутри окна
            if active_sub.end_date <= attendance_entries[-1]['date']:
                for idx, entry in enumerate(attendance_entries):
                    if entry['date'] <= active_sub.end_date:
                        subscription_end_index = idx
        children_data.append({
            'child': child,
            'initials': initials,
            'birth_year': child.birth_year,
            'rank': rank_str,
            'sessions_left': sessions_left,
            'sessions_total': sessions_total,
            'debt': debt,
            'subscription_end': active_sub.end_date if active_sub else None,
            'subscription_end_soon': subscription_end_soon,
            'status': child.status,
            'attendance_entries': attendance_entries,
            'subscription_end_index': subscription_end_index,
        })

    context = {
        'groups': Group.objects.filter(is_active=True),
        'selected_group': group,
        'days': days,
        'week_data': week_data,  # для отображения подписей недель в шапке
        'week_start': week_start,
        'week_start_prev': (week_start - timedelta(days=14)).strftime('%Y-%m-%d'),
        'week_start_next': (week_start + timedelta(days=14)).strftime('%Y-%m-%d'),
        'children_data': children_data,
        'today': today,
        'period_end': period_end,
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

    # Если пришёл пустой статус — удаляем все отметки на эту дату
    if status == '':
        deleted_count, _ = Attendance.objects.filter(child=child, date=date).delete()
        return JsonResponse({'success': True, 'status': '', 'deleted': deleted_count > 0})

    valid_statuses = [s[0] for s in Attendance.Status.choices]
    if status not in valid_statuses:
        return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)

    # Ищем существующую отметку (по ребёнку и дате)
    attendance = Attendance.objects.filter(child=child, date=date).first()
    if attendance:
        attendance.status = status
        attendance.save()
    else:
        attendance = Attendance.objects.create(
            child=child,
            date=date,
            status=status
        )

    return JsonResponse({'success': True, 'status': attendance.status})