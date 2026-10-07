# 1. Клонировать/скопировать проект
cd /opt/crm

# 2. Создать .env из шаблона
cp .env.example .env
nano .env   # прописать SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS

# 3. Собрать и запустить
docker compose up -d --build

# 4. Создать админа
docker exec -it crm-web python manage.py createsuperuser

# 5. Проверить логи
docker compose logs -f web

# 6. Настроить автобэкапы
sudo crontab -e
# Добавить строку:
# 0 3 * * *  /opt/crm/backup.sh >> /var/log/crm_backup.log 2>&1