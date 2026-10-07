#!/bin/bash
set -e

echo "🔄 Применяю миграции..."
python manage.py migrate --noinput

echo "📦 Собираю статику..."
python manage.py collectstatic --noinput

echo "🚀 Запускаю gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 6 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -