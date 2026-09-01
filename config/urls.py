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
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from crm import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.attendance_page, name='home'),
    path('login/', views.login_page, name='login'),
    path('logout/', views.logout_page, name='logout'),
    path('attendance/', views.attendance_page, name='attendance'),
    path('children/<int:pk>/edit/', views.child_edit, name='child_edit'),
    path('applications/', views.applications_page, name='applications'),
    path('newcomers/', views.newcomers_page, name='newcomers'),
    path('calendar/', views.calendar_page, name='calendar'),
    path('search/', views.search_page, name='search'),
    path('statistics/', views.statistics_page, name='statistics'),
    path('payments/', views.payments_page, name='payments'),
    path('expenses/', views.expenses_page, name='expenses'),
    path('competitions/', views.competitions_page, name='competitions'),
    path('competitions/<int:pk>/export/', views.competition_export, name='competition_export'),
    path('notifications/', views.notifications_page, name='notifications'),
    path('boss/', views.boss_page, name='boss'),
    path('users/', views.users_page, name='users'),
    path('profile/', views.profile_page, name='profile'),
    path('backup/export/', views.backup_export, name='backup_export'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
