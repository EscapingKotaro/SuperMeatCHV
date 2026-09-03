"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from crm import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.app_page, name='home'),
    
    path('login/', views.login_page, name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('test/<str:page>/', views.app_page, name='app_page'),

    
    path('crm/attendance/', views.attendance_view, name='attendance'),
    path('crm/attendance/update/', views.update_attendance, name='attendance_update'),
    path('revenue-forecast/', views.revenue_forecast_view, name='revenue_forecast'),

    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('users/<int:pk>/reset-password/', views.user_reset_password, name='user_reset_password'),

    # Смена пароля для любого авторизованного пользователя
    path('profile/change-password/', views.change_password, name='change_password'),
# Карточка ребенка
    path('child/<int:child_id>/', views.child_card_view, name='child_card'),
    path('child/<int:child_id>/edit/', views.child_edit_view, name='child_edit'),
    path('child/create/', views.child_create_view, name='child_create'),
    path('child/<int:child_id>/delete/', views.child_delete_view, name='child_delete'),

    # API для добавления абонемента
    path('child/<int:child_id>/subscription/add/', views.add_subscription_view, name='add_subscription'),

    # Тренеры
    path('trainers/', views.trainer_list_view, name='trainer_list'),
    path('trainers/create/', views.trainer_create_view, name='trainer_create'),
    path('trainers/<int:pk>/edit/', views.trainer_edit_view, name='trainer_edit'),
    path('trainers/<int:pk>/delete/', views.trainer_delete_view, name='trainer_delete'),

    # Группы
    path('groups/', views.group_list_view, name='group_list'),
    path('groups/create/', views.group_create_view, name='group_create'),
    path('groups/<int:pk>/edit/', views.group_edit_view, name='group_edit'),
    path('groups/<int:pk>/delete/', views.group_delete_view, name='group_delete'),
]

