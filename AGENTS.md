# AGENTS.md

## Project

Django CRM-система для гимнастического клуба ("Высота CRM"). Шаблонный UI на Tailwind CSS (CDN), SQLite3, без REST API. Русский интерфейс (`ru-ru`, `Europe/Moscow`).

## Quick Start

```bash
python manage.py migrate
python manage.py seed_demo          # demo-данные: boss/senior/admin, пароль Demo12345!
python manage.py runserver
```

## Commands

| Task | Command |
|------|---------|
| Тесты | `python manage.py test crm` |
| Миграции | `python manage.py makemigrations && python manage.py migrate` |
| Demo-данные | `python manage.py seed_demo` |
| Тестовые данные | `python manage.py fill_test_data` |
| Сбор статики | `python manage.py collectstatic` |

**Нет:** линтеров, форматтеров, typecheck, pytest, CI/CD, Dockerfile, lockfile.

## Architecture

- `config/` — Django-проект (settings, urls, wsgi)
- `crm/` — Единственное приложение: модели (22), views (1793 строки), формы, шаблоны (31), статика
- `crm/models.py` — все модели в одном файле
- `crm/views.py` — все views в одном файле (~1800 строк)
- `crm/forms.py` — все формы в одном файле
- `crm/admin.py` — кастомная админка с `RoleGate`

## Gotchas

- **Два view для табеля:** `attendance_view` (AJAX) и `attendance_page` (полная страница) — не путать
- **Дублированные методы:** `age_display()` определён дважды в `Child` (строки ~184 и ~204)
- **Wildcard import:** `from .models import *` в `views.py` — импорты дублируются в нескольких местах файла
- **Роли:** `manager=0, senior=1, boss=2`. Кастомный декоратор `@role_required` + `RoleGate` в admin. Суперпользователь автоматически boss
- **Auth:** `LOGIN_URL='login'`, `LOGIN_REDIRECT_URL='attendance'`. Remember me = 2 недели
- **Нет API** — всё через Django forms + шаблоны. `DATABASE_RECOMMENDATIONS.md` описывает будущую архитектуру БД для API
- **Tailwind через CDN** — нет build-шага, стили в `crm/static/crm/app.css`

## DB

SQLite3 по умолчанию. PostgreSQL при наличии `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` в env.
