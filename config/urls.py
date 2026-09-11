from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path

from crm import views
from crm import staff_views
from crm import intake_views
from crm import team_views
from crm import certificate_views


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
    path("attendance/reason/", views.attendance_reason_view, name="attendance_reason"),
    path("attendance/move-class/", views.move_class_view, name="move_class"),
    path("attendance/assign-trainer/", views.assign_lesson_trainer_view, name="assign_lesson_trainer"),

    # Дети / спортсмены
    path("children/create/", views.child_create_view, name="child_create"),
    path("children/<int:child_id>/", views.child_card_view, name="child_card"),
    path("children/<int:child_id>/certificate/", views.child_certificate_view, name="child_certificate"),
    path("children/<int:child_id>/certificate/manage/", certificate_views.child_certificate_manage_view, name="child_certificate_manage"),
    path("children/<int:child_id>/documents/<str:kind>/", certificate_views.child_document_view, name="child_document"),
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
    path("payments/history/", views.payment_history_view, name="payment_history"),

    path("subscriptions/cancel/", views.cancel_subscription_view, name="cancel_subscription"),

    # Расходы
    path("expenses/", views.expenses_page, name="expenses"),

    # Зарплаты
    path("salaries/", views.salaries_view, name="salaries"),
    path("salaries/export/", views.salaries_export_view, name="salaries_export"),

    # Соревнования
    path("competitions/", views.competitions_page, name="competitions"),
    path("competitions/<int:pk>/export/", views.competition_export, name="competition_export"),

    path("camps/", views.camps_page, name="camps"),
    path("competition-documents/<int:pk>/", views.competition_document_download, name="competition_document_download"),

    # Уведомления
    path("notifications/", views.notifications_page, name="notifications"),

    # Заявки
    path("applications/", intake_views.applications_page, name="applications"),

    # Новички
    path("newcomers/", intake_views.newcomers_page, name="newcomers"),

    # Календарь
    path("calendar/", views.calendar_page, name="calendar"),

    # Клиенты
    path("clients/", team_views.clients_page, name="clients"),

    # Поиск
    path("search/", views.search_page, name="search"),

    # Тренеры
    path("trainers/", team_views.trainer_list_view, name="trainer_list"),
    path("trainers/create/", team_views.trainer_create_view, name="trainer_create"),
    path("trainers/<int:pk>/edit/", team_views.trainer_edit_view, name="trainer_edit"),
    path("trainers/<int:pk>/delete/", team_views.trainer_delete_view, name="trainer_delete"),

    # Группы
    path("groups/", team_views.group_list_view, name="group_list"),
    path("groups/create/", team_views.group_create_view, name="group_create"),
    path("groups/<int:pk>/edit/", team_views.group_edit_view, name="group_edit"),
    path("groups/<int:pk>/delete/", team_views.group_delete_view, name="group_delete"),

    # Руководитель
    path("boss/", views.boss_page, name="boss"),
    path("boss/logs/export/", views.boss_logs_export, name="boss_logs_export"),

    # Пользователи
    path("users/", views.users_page, name="users"),
    path("users/<int:user_id>/update/", staff_views.staff_update_view, name="user_update"),

    # Профиль
    path("profile/", views.profile_page, name="profile"),

    # Backup
    path("backup/export/", views.backup_export, name="backup_export"),
]