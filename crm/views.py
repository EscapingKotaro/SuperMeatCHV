from django.shortcuts import render


PAGES = {
    "statistics": ("Статистика", "Главные показатели клуба за август"),
    "payments": ("Продления", "Кому пора напомнить об оплате"),
    "expenses": ("Расходы", "Бытовые закупки и другие расходы"),
    "competitions": ("Соревнования", "Баллы, места и история выступлений"),
    "notifications": ("Уведомления", "Задачи и события, требующие внимания"),
    "boss": ("Для руководителя", "Выручка, KPI и работа команды"),
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
from .models import Child, Group, ScheduleSlot, Attendance
from .forms import ChildForm

def generate_class_dates(group, start_date, limit=60):
    """Генерирует список дат занятий"""
    slots = ScheduleSlot.objects.filter(group=group).order_by('weekday', 'start_time')
    if not slots:
        return []
    
    dates = []
    current = start_date
    end_limit = start_date + timedelta(days=180)
    
    while current <= end_limit and len(dates) < limit:
        for slot in slots:
            if current.weekday() == slot.weekday:
                dates.append(current)
        current += timedelta(days=1)
    
    return sorted(list(set(dates)))


@login_required
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
            return render(request, 'crm/attendance.html', {
                'groups': Group.objects.none(),
                'selected_group': None,
            })

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

    # 3. Генерируем даты
    start_of_week = ref_date - timedelta(days=ref_date.weekday())
    all_class_dates = generate_class_dates(group, start_of_week, limit=60)

    if not all_class_dates:
        return render(request, 'crm/attendance.html', {
            'groups': Group.objects.filter(is_active=True),
            'selected_group': group,
            'week_data': [],
            'children_data': [],
            'ref_date': ref_date,
            'error': 'Нет расписания'
        })

    # 4. Находим индекс
    current_index = 0
    for i, d in enumerate(all_class_dates):
        if d >= ref_date:
            current_index = i
            break

    if all_class_dates[-1] < ref_date:
        current_index = len(all_class_dates) - 1

    # 5. Формируем окно
    start_idx = max(0, current_index - 4)
    end_idx = min(len(all_class_dates), current_index + 6)
    window_dates = all_class_dates[start_idx:end_idx]

    # 6. Подготовка данных о днях
    week_data = []
    for d in window_dates:
        slots_today = ScheduleSlot.objects.filter(group=group, weekday=d.weekday())
        start_time = slots_today.first().start_time if slots_today else None
        week_data.append({
            'date': d,
            'start_time': start_time,
            'is_today': d == today
        })

    # 7. ПОЛУЧАЕМ ДЕТЕЙ (с учетом архива)
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

    # 8. СОРТИРОВКА (превращаем в список и сортируем)
    children_list = list(children_qs)
    
    if sort_by == 'sessions':
        children_list.sort(key=lambda c: c.sessions_left(), reverse=True)
    elif sort_by == 'debt':
        children_list.sort(key=lambda c: c.debt(), reverse=True)
    else:
        children_list.sort(key=lambda c: (c.last_name.lower(), c.first_name.lower()))

    children_data = []
    for child in children_list:
        active_sub = child.active_subscription()
        projected_end = child.projected_end_date()

        att_map = {}
        for att in child.attendances.filter(date__in=window_dates):
            att_map[att.date] = att.status

        entries = []
        sub_end_index = None
        subscription_ending_soon = False

        for idx, wd in enumerate(week_data):
            status = att_map.get(wd['date'], '')
            entries.append({'date': wd['date'], 'status': status})
            
            if projected_end and wd['date'] == projected_end:
                sub_end_index = idx
            
            if projected_end and wd['date'] >= projected_end - timedelta(days=7) and wd['date'] <= projected_end:
                subscription_ending_soon = True

        # Авто-перевод в потерянные, если пробный истек (только для не-архивных)
        if not show_archived and child.is_trial_expired():
            child.mark_as_lost()

        children_data.append({
            'child': child,
            'initials': f"{child.last_name[0]}{child.first_name[0]}".upper(),
            'age': child.age_display(),
            'sessions_left': child.sessions_left(),
            'sessions_total': active_sub.sessions_total if active_sub else 0,
            'debt': child.debt(),
            'has_certificate': child.has_certificate(),
            'discount_percent': child.discount_percent,
            'subscription_end': active_sub.end_date if active_sub else None,
            'subscription_end_index': sub_end_index,
            'subscription_ending_soon': subscription_ending_soon,
            'is_trial': child.status == Child.Status.TRIAL,
            'is_archived': child.status in [Child.Status.ARCHIVED, Child.Status.LOST],
            'attendance_entries': entries,
        })

    # 9. Переключатель дат
    if len(window_dates) >= 2:
        window_span = (window_dates[-1] - window_dates[0]).days
    else:
        window_span = 7

    prev_ref = (window_dates[0] - timedelta(days=window_span)).strftime('%Y-%m-%d') if window_dates else (today - timedelta(days=7)).strftime('%Y-%m-%d')
    next_ref = (window_dates[-1] + timedelta(days=window_span)).strftime('%Y-%m-%d') if window_dates else (today + timedelta(days=7)).strftime('%Y-%m-%d')

    # Базовые параметры для ссылок, чтобы сортировка не слетала
    base_params = f"group_id={group.id}&ref_date={{}}&sort={sort_by}"
    if show_archived:
        base_params += "&show_archived=1"

    context = {
        'groups': Group.objects.filter(is_active=True),
        'selected_group': group,
        'trainer': trainer,
        'week_data': week_data,
        'children_data': children_data,
        'ref_date': ref_date,
        'prev_ref': prev_ref,
        'next_ref': next_ref,
        'today': today,
        'sort_by': sort_by,
        'show_archived': show_archived,
        'base_params': base_params,
        'page': 'attendance'
    }
    return render(request, 'crm/attendance.html', context)


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



from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from .models import User
import random
import string

# --- Декораторы для проверки ролей ---
def is_senior_or_boss(user):
    return user.is_authenticated and user.role in [User.Role.SENIOR_MANAGER, User.Role.CHIEF, User.Role.ADMIN]

def senior_manager_required(view_func):
    return user_passes_test(is_senior_or_boss, login_url='/')(view_func)

# --- 1. Список пользователей ---


@login_required
@senior_manager_required
def user_list(request):
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'crm/users/user_list.html', {'users': users})

# --- 2. Создание пользователя ---
@login_required
@senior_manager_required
def user_create(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Пользователь с таким именем уже существует.')
            return redirect('user_list')

        user = User.objects.create_user(
            username=username,
            password=password,
            role=role
        )
        messages.success(request, f'Пользователь {username} успешно создан.')
        return redirect('user_list')

    return render(request, 'crm/users/user_form.html', {'action': 'create'})

# --- 3. Удаление пользователя ---
@login_required
@senior_manager_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, 'Нельзя удалить самого себя.')
    else:
        user.delete()
        messages.success(request, 'Пользователь удален.')
    return redirect('user_list')

# --- 4. Сброс пароля администратором ---
@login_required
@senior_manager_required
def user_reset_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.set_password(new_password)
    user.save()

    messages.success(request, f'Пароль для {user.username} сброшен. Новый пароль: {new_password}')
    return redirect('user_list')

# --- 5. Смена пароля самим пользователем ---
@login_required
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')

        if not request.user.check_password(old_password):
            messages.error(request, 'Неверный текущий пароль.')
        else:
            request.user.set_password(new_password)
            request.user.save()
            # Обновляем сессию, чтобы не выкинуло из системы
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Пароль успешно изменен.')
            return redirect('profile') # или куда ведет ссылка "Мой профиль"

    return render(request, 'crm/users/change_password.html')



from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import Child, Group

# views.py

from .models import Child, Group, calculate_projected_end_date # Не забудь импорт функции!

@login_required
def revenue_forecast_view(request):
    today = timezone.localdate()
    days = []
    processed_child_ids = set()

    for i in range(4):
        current_date = today + timedelta(days=i)
        
        children = Child.objects.filter(status=Child.Status.ACTIVE).select_related('group')
        
        urgent_list = []
        one_left_list = []
        forecast_list = []

        for child in children:
            if child.id in processed_child_ids:
                continue

            active_sub = child.active_subscription()
            if not active_sub:
                continue

            left_on_date = child.sessions_left_on_date(current_date)

            # Блок 1: Срочно (0 занятий)
            if left_on_date == 0:
                urgent_list.append({
                    'name': f"{child.last_name} {child.first_name}",
                    'parent_name': child.parent_name,
                    'parent_phone': child.parent_phone,
                    'amount': active_sub.price
                })
                processed_child_ids.add(child.id)
                continue

            # Блок 2: Осталось 1 занятие
            if left_on_date == 1:
                one_left_list.append({
                    'name': f"{child.last_name} {child.first_name}",
                    'parent_name': child.parent_name,
                    'parent_phone': child.parent_phone,
                    'amount': active_sub.price
                })
                processed_child_ids.add(child.id)
                continue

            # Блок 3: Прогноз (до окончания менее 5 календарных дней)
            proj_end = calculate_projected_end_date(child.group, current_date, left_on_date)
            if proj_end and (proj_end - current_date).days < 5:
                forecast_list.append({
                    'name': f"{child.last_name} {child.first_name}",
                    'parent_name': child.parent_name,
                    'parent_phone': child.parent_phone,
                    'amount': active_sub.price
                })
                processed_child_ids.add(child.id)

        total_day = sum(item['amount'] for item in urgent_list + one_left_list + forecast_list)

        days.append({
            'date': current_date,
            'weekday': current_date.strftime("%A"),
            'total': total_day,
            'urgent': urgent_list,
            'one_left': one_left_list,
            'forecast': forecast_list,
        })

    context = {
        'days': days,
        'title': 'Прогноз доходов',
        'subtitle': 'Ожидаемые продления на ближайшие 4 дня',
        'page': 'revenue_forecast'
    }
    return render(request, 'crm/revenue_forecast.html', context)


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
    attendances = child.attendances.all().order_by('-date')[:50]
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

    # === HEAT-MAP: последние 365 дней ===
        # === HEAT-MAP: последние 180 дней ===
    today = timezone.localdate()
    days_back = 180
    year_ago = today - timedelta(days=days_back - 1)

    # Получаем все посещения за период
    period_attendances = {
        att.date: att.status
        for att in child.attendances.filter(date__gte=year_ago)
    }

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
            if date > end_date:
                week.append(None)
            else:
                status = period_attendances.get(date)
                week.append({
                    'date': date,
                    'status': status,
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

    if request.method == 'POST' and 'change_group' in request.POST:
        new_group_id = request.POST.get('new_group')
        if new_group_id:
            new_group = get_object_or_404(Group, id=new_group_id)
            child.group = new_group
            child.save(update_fields=['group'])
            messages.success(request, f'Ребенок переведен в группу "{new_group.name}"')
            return redirect('child_card', child_id=child.id)

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
        'page': 'child_card'
    }
    return render(request, 'crm/child_card.html', context)


@login_required
def child_edit_view(request, child_id):
    child = get_object_or_404(Child, id=child_id)
    if request.method == 'POST':
        form = ChildForm(request.POST, request.FILES, instance=child)
        if form.is_valid():
            form.save()
            messages.success(request, 'Данные ребенка обновлены')
            return redirect('child_card', child_id=child.id)
    else:
        form = ChildForm(instance=child)
    return render(request, 'crm/child_edit.html', {'form': form, 'child': child, 'page': 'child_edit'})


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
    if request.method == 'POST':
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.child = child
            sub.save()
            messages.success(request, 'Абонемент добавлен')
            return redirect('child_card', child_id=child.id)
    else:
        form = SubscriptionForm()
    return render(request, 'crm/add_subscription.html', {'form': form, 'child': child, 'page': 'add_subscription'})


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Trainer, Group, ScheduleSlot
from .forms import TrainerForm, GroupForm, ScheduleSlotFormSet

# ==================== ТРЕНЕРЫ ====================

@login_required
def trainer_list_view(request):
    """Список тренеров"""
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
    """Список групп"""
    groups = Group.objects.select_related('trainer').prefetch_related('schedule', 'children').order_by('name')
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
    return render(request, 'crm/group_edit.html', context)

@login_required
def group_edit_view(request, pk):
    """Редактирование группы с расписанием"""
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
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
    month_str = request.GET.get('month')
    try:
        month_start = datetime.strptime(month_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        month_start = today.replace(day=1)
    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
    return month_start, month_end, today

def _sessions_held(group, month_start, month_end, today):
    """Сколько занятий прошло по расписанию группы в месяце (до сегодня)."""
    weekdays = set(ScheduleSlot.objects.filter(group=group).values_list('weekday', flat=True))
    last = min(month_end, today)
    count, d = 0, month_start
    while d <= last:
        if d.weekday() in weekdays:
            count += 1
        d += timedelta(days=1)
    return count

def build_salary_data(month_start, month_end):
    """Собирает таблицу ЗП в формате как в Excel."""
    summary_rows, grand_total = [], 0
    trainers = []

    for trainer in Trainer.objects.prefetch_related('groups', 'salary_adjustments'):
        rows, total = [], 0
        for group in trainer.groups.all():
            rate = group.salary_rate or 0
            visits = Attendance.objects.filter(
                child__group=group, status='present',
                date__gte=month_start, date__lte=month_end).count()
            summa = Decimal(rate) * visits
            rows.append({'name': group.name, 'rate': rate, 'visits': visits, 'total': summa})
            summary_rows.append({'name': group.name, 'rate': rate, 'visits': visits, 'total': summa})
            total += summa

        for adj in trainer.salary_adjustments.filter(month=month_start):
            rows.append({'name': adj.title, 'rate': '', 'visits': '', 'total': adj.amount})
            summary_rows.append({'name': adj.title, 'rate': '', 'visits': '', 'total': adj.amount})
            total += adj.amount

        if rows:
            trainers.append({'trainer': trainer, 'rows': rows, 'total': total})
            grand_total += total

    return {'summary_rows': summary_rows, 'grand_total': grand_total, 'trainers': trainers}


@login_required
def statistics_view(request):
    month_start, month_end, today = _month_range(request)

    children = Child.objects.all()
    total_children = children.count()
    active_children = children.filter(status=Child.Status.ACTIVE).count()

    new_qs = children.filter(created_at__date__gte=month_start, created_at__date__lte=month_end)
    new_count = new_qs.count()
    new_kept = new_qs.filter(status=Child.Status.ACTIVE).count()
    left_count = children.filter(
        status__in=[Child.Status.LOST, Child.Status.ARCHIVED],
        archived_at__gte=month_start, archived_at__lte=month_end).count()

    # Выручка
    revenue_today = Payment.objects.filter(date=today).aggregate(s=Sum('amount'))['s'] or 0
    revenue_month = Payment.objects.filter(
        date__gte=month_start, date__lte=month_end).aggregate(s=Sum('amount'))['s'] or 0
    # Прогноз: факт месяца + ожидаемые продления (абонементы, кончающиеся до конца месяца)
    expected = Subscription.objects.filter(
        end_date__gte=today, end_date__lte=month_end).aggregate(s=Sum('price'))['s'] or 0
    potential = Decimal(revenue_month) + Decimal(expected)

    target = RevenueTarget.objects.filter(month=month_start).first()

    # По группам: спортсмены, посещения, посещаемость
    groups_stats = []
    for g in Group.objects.filter(is_active=True).select_related('trainer'):
        kids = g.children.count()
        present = Attendance.objects.filter(
            child__group=g, status='present',
            date__gte=month_start, date__lte=month_end).count()
        absent = Attendance.objects.filter(
            child__group=g, status='absent',
            date__gte=month_start, date__lte=month_end).count()
        sessions = _sessions_held(g, month_start, month_end, today)
        capacity = kids * sessions
        attendance_pct = round(present * 100 / capacity) if capacity else 0
        groups_stats.append({
            'group': g, 'kids': kids, 'present': present, 'absent': absent,
            'sessions': sessions, 'attendance_pct': attendance_pct,
        })

    # По тренерам: ушедшие + посещаемость
    trainers_stats = []
    for t in Trainer.objects.filter(is_active=True):
        t_left = children.filter(
            group__trainer=t, status__in=[Child.Status.LOST, Child.Status.ARCHIVED],
            archived_at__gte=month_start, archived_at__lte=month_end).count()
        t_groups = [gs for gs in groups_stats if gs['group'].trainer_id == t.id]
        t_present = sum(gs['present'] for gs in t_groups)
        t_capacity = sum(gs['kids'] * gs['sessions'] for gs in t_groups)
        trainers_stats.append({
            'trainer': t,
            'left': t_left,
            'present': t_present,
            'attendance_pct': round(t_present * 100 / t_capacity) if t_capacity else 0,
        })

    context = {
        'month_start': month_start, 'month_end': month_end, 'today': today,
        'total_children': total_children, 'active_children': active_children,
        'new_count': new_count, 'new_kept': new_count - 0 and new_kept,
        'left_count': left_count,
        'revenue_today': revenue_today, 'revenue_month': revenue_month,
        'potential': potential, 'target': target,
        'groups_stats': groups_stats, 'trainers_stats': trainers_stats,
        'title': 'Статистика', 'page': 'statistics',
    }
    return render(request, 'crm/statistics.html', context)


@login_required
def salaries_view(request):
    month_start, month_end, today = _month_range(request)
    data = build_salary_data(month_start, month_end)
    context = {**data, 'month_start': month_start, 'month_end': month_end,
               'title': 'ЗП тренеров', 'page': 'salaries'}
    return render(request, 'crm/salaries.html', context)


@login_required
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


@login_required
def payments_table_view(request):
    month_start, month_end, today = _month_range(request)
    payments = Payment.objects.filter(
        date__gte=month_start, date__lte=month_end
    ).select_related('child', 'child__group', 'created_by', 'subscription').order_by('-date')
    total = payments.aggregate(s=Sum('amount'))['s'] or 0
    context = {'payments': payments, 'total': total,
               'month_start': month_start, 'month_end': month_end,
               'title': 'Предварительные оплаты', 'page': 'payments_table'}
    return render(request, 'crm/payments_table.html', context)


@login_required
def expenses_table_view(request):
    month_start, month_end, today = _month_range(request)
    if request.method == 'POST':
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        if title and amount:
            Expense.objects.create(title=title, amount=amount, created_by=request.user)
            messages.success(request, 'Расход добавлен')
            return redirect('expenses_table')
    expenses = Expense.objects.filter(
        date__gte=month_start, date__lte=month_end).order_by('-date')
    total = expenses.aggregate(s=Sum('amount'))['s'] or 0
    context = {'expenses': expenses, 'total': total,
               'month_start': month_start, 'month_end': month_end,
               'title': 'Расходы', 'page': 'expenses_table'}
    return render(request, 'crm/expenses_table.html', context)
