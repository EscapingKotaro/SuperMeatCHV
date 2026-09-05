from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path

from crm import views


urlpatterns = [
    # Django admin
    path("admin/", admin.site.urls),

    # Auth
    path("login/", views.login_page, name="login"),
    path("logout/", views.logout_page, name="logout"),

    # Главная / посещаемость
    path("", login_required(views.attendance_view, login_url="login"), name="home"),
    path("attendance/", login_required(views.attendance_view, login_url="login"), name="attendance"),
    path("attendance/mark/", views.mark_attendance_view, name="mark_attendance"),
    path("attendance/cancel/", views.cancel_attendance_view, name="cancel_attendance"),

    # Дети / спортсмены
    path("children/create/", views.child_create_view, name="child_create"),
    path("children/<int:child_id>/", views.child_card_view, name="child_card"),
    path("children/<int:child_id>/edit/", views.child_edit_view, name="child_edit"),
    path("children/<int:child_id>/delete/", views.child_delete_view, name="child_delete"),
    path("children/<int:child_id>/archive/", views.archive_child_view, name="archive_child"),
    path("children/<int:child_id>/restore/", views.restore_child_view, name="restore_child"),
    path("children/<int:child_id>/subscription/add/", views.add_subscription_view, name="add_subscription"),

    # Группы / пробные ученики
    path("groups/<int:group_id>/trial-child/", views.add_trial_child_view, name="add_trial_child"),

    # Статистика
    path("statistics/", views.statistics_view, name="statistics"),

    # Прогноз доходов
    path("revenue-forecast/", views.revenue_forecast_view, name="revenue_forecast"),

    # Оплаты / абонементы
    path("payments/", views.payments_page, name="payments"),
    path("payments/table/", views.payments_table_view, name="payments_table"),

    # Расходы
    path("expenses/", views.expenses_page, name="expenses"),
    path("expenses/table/", views.expenses_table_view, name="expenses_table"),

    # Зарплаты
    path("salaries/", views.salaries_view, name="salaries"),
    path("salaries/export/", views.salaries_export_view, name="salaries_export"),

    # Соревнования
    path("competitions/", views.competitions_page, name="competitions"),
    path("competitions/<int:pk>/export/", views.competition_export, name="competition_export"),

    # Уведомления
    path("notifications/", views.notifications_page, name="notifications"),

    # Заявки
    path("applications/", views.applications_page, name="applications"),

    # Новички
    path("newcomers/", views.newcomers_page, name="newcomers"),

    # Календарь
    path("calendar/", views.calendar_page, name="calendar"),

    # Поиск
    path("search/", views.search_page, name="search"),

    # Тренеры
    path("trainers/", views.trainer_list_view, name="trainer_list"),
    path("trainers/create/", views.trainer_create_view, name="trainer_create"),
    path("trainers/<int:pk>/edit/", views.trainer_edit_view, name="trainer_edit"),
    path("trainers/<int:pk>/delete/", views.trainer_delete_view, name="trainer_delete"),

    # Группы
    path("groups/", views.group_list_view, name="group_list"),
    path("groups/create/", views.group_create_view, name="group_create"),
    path("groups/<int:pk>/edit/", views.group_edit_view, name="group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete_view, name="group_delete"),

    # Руководитель
    path("boss/", views.boss_page, name="boss"),

    # Пользователи
    path("users/", views.users_page, name="users"),

    # Профиль
    path("profile/", views.profile_page, name="profile"),

    # Backup
    path("backup/export/", views.backup_export, name="backup_export"),
]