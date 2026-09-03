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



def generate_class_dates(group, start_date, limit=50):
    """
    Генерирует список дат занятий начиная с start_date.
    limit - сколько дат вперед генерировать.
    """
    slots = ScheduleSlot.objects.filter(group=group).order_by('weekday', 'start_time')
    if not slots:
        return []

    dates = []
    # Начинаем генерацию с указанной даты
    current = start_date

    # Защита от бесконечного цикла: идем вперед, пока не наберем limit дат
    # или не пройдем 6 месяцев (на всякий случай)
    end_limit = start_date + timedelta(days=180)

    while current <= end_limit and len(dates) < limit:
        for slot in slots:
            if current.weekday() == slot.weekday:
                dates.append(current)
        current += timedelta(days=1)

    # Убираем дубликаты (если несколько слотов в один день) и сортируем
    return sorted(list(set(dates)))
@login_required
def attendance_view(request):
    group_id = request.GET.get('group_id')
    ref_date_str = request.GET.get('ref_date')

    # 1. Группа
    if group_id:
        group = get_object_or_404(Group, id=group_id)
    else:
        group = Group.objects.filter(is_active=True).first()
        if not group:
             return render(request, 'crm/attendance.html', {'groups': Group.objects.none(), 'selected_group': None})

    trainer = group.trainer if group else None

    # 2. Опорная дата
    today = timezone.localdate()
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

    # 5. Формируем окно: 4 назад, 6 вперед (10 занятий)
    start_idx = max(0, current_index - 4)
    end_idx = min(len(all_class_dates), current_index + 6)
    window_dates = all_class_dates[start_idx:end_idx]

    # 6. Подготовка данных
    week_data = []
    for d in window_dates:
        slots_today = ScheduleSlot.objects.filter(group=group, weekday=d.weekday())
        start_time = slots_today.first().start_time if slots_today else None
        week_data.append({
            'date': d,
            'start_time': start_time,
            'is_today': d == today
        })

    # Дети
    children = Child.objects.filter(group=group).select_related('group__trainer').prefetch_related(
        'subscriptions', 'payments', 'attendances', 'ranks'
    ).order_by('last_name', 'first_name')

    children_data = []
    for child in children:
        active_sub = child.active_subscription()
        projected_end = child.projected_end_date()

        att_map = {}
        for att in child.attendances.filter(date__in=window_dates):
            att_map[att.date] = att.status

        entries = []
        sub_end_index = None

        for idx, wd in enumerate(week_data):
            status = att_map.get(wd['date'], '')
            entries.append({'date': wd['date'], 'status': status})
            if projected_end and wd['date'] == projected_end:
                sub_end_index = idx

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
            'attendance_entries': entries,
        })

    # 7. Переключатель дат: сдвигаем на размер окна
    if len(window_dates) >= 2:
        window_span = (window_dates[-2] - window_dates[0]).days
    else:
        window_span = 7  # Если одно занятие, сдвигаем на неделю

    prev_ref = (window_dates[0] - timedelta(days=window_span)).strftime('%Y-%m-%d') if window_dates else (today - timedelta(days=7)).strftime('%Y-%m-%d')
    next_ref = (window_dates[-1] + timedelta(days=window_span)).strftime('%Y-%m-%d') if window_dates else (today + timedelta(days=7)).strftime('%Y-%m-%d')

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
        'page': 'attendance'
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
    """Просмотр карточки ребенка"""
    child = get_object_or_404(Child, id=child_id)

    # Получаем связанные данные
    subscriptions = child.subscriptions.all().order_by('-start_date')
    attendances = child.attendances.all().order_by('-date')[:50]  # Последние 50 посещений
    ranks = child.ranks.all().order_by('-year')

    # Статистика
    active_sub = child.active_subscription()
    sessions_left = child.sessions_left()
    debt = child.debt()

    context = {
        'child': child,
        'subscriptions': subscriptions,
        'attendances': attendances,
        'ranks': ranks,
        'active_sub': active_sub,
        'sessions_left': sessions_left,
        'debt': debt,
        'page': 'child_card'
    }
    return render(request, 'crm/child_card.html', context)

@login_required
def child_edit_view(request, child_id):
    """Редактирование ребенка"""
    child = get_object_or_404(Child, id=child_id)

    if request.method == 'POST':
        form = ChildForm(request.POST, request.FILES, instance=child)
        if form.is_valid():
            form.save()
            messages.success(request, 'Данные ребенка обновлены')
            return redirect('child_card', child_id=child.id)
    else:
        form = ChildForm(instance=child)

    context = {
        'form': form,
        'child': child,
        'page': 'child_edit'
    }
    return render(request, 'crm/child_edit.html', context)

@login_required
def child_create_view(request):
    """Создание нового ребенка"""
    if request.method == 'POST':
        form = ChildForm(request.POST, request.FILES)
        if form.is_valid():
            child = form.save()
            messages.success(request, f'Ребенок {child.last_name} {child.first_name} добавлен')
            return redirect('child_card', child_id=child.id)
    else:
        form = ChildForm()

    context = {
        'form': form,
        'page': 'child_create'
    }
    return render(request, 'crm/child_edit.html', context)

@login_required
def child_delete_view(request, child_id):
    """Удаление ребенка"""
    child = get_object_or_404(Child, id=child_id)

    if request.method == 'POST':
        child_name = f"{child.last_name} {child.first_name}"
        child.delete()
        messages.success(request, f'Ребенок {child_name} удален')
        return redirect('attendance')

    context = {
        'child': child,
        'page': 'child_delete'
    }
    return render(request, 'crm/child_delete.html', context)

@login_required
def add_subscription_view(request, child_id):
    """Добавление абонемента"""
    child = get_object_or_404(Child, id=child_id)

    if request.method == 'POST':
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            subscription = form.save(commit=False)
            subscription.child = child
            subscription.save()
            messages.success(request, 'Абонемент добавлен')
            return redirect('child_card', child_id=child.id)
    else:
        form = SubscriptionForm()

    context = {
        'form': form,
        'child': child,
        'page': 'add_subscription'
    }
    return render(request, 'crm/add_subscription.html', context)


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
