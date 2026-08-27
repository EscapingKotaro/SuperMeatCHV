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
