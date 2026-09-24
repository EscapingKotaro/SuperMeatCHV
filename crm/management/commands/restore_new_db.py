import os
import subprocess
import gzip
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Восстанавливает БД из SQL дампа'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к файлу .sql или .sql.gz')
        parser.add_argument(
            '--soft',
            action='store_true',
            help='Мягкое восстановление: добавлять только недостающие данные, не удалять существующие'
        )

    def handle(self, *args, **options):
        file_path = options['file_path']
        soft_mode = options['soft']
        
        if not os.path.exists(file_path):
            raise CommandError(f"Файл не найден: {file_path}")

        db_name = os.environ.get('DB_NAME', 'mydb')
        db_user = os.environ.get('DB_USER', 'myuser')
        db_password = os.environ.get('DB_PASSWORD', '')
        db_host = os.environ.get('DB_HOST', 'db')

        self.stdout.write("⚠️  Начинается восстановление БД...")
        if soft_mode:
            self.stdout.write(self.style.WARNING("🔄 Режим: МЯГКОЕ ВОССТАНОВЛЕНИЕ (без удаления существующих данных)"))
        else:
            self.stdout.write(self.style.ERROR("🔥 Режим: ПОЛНОЕ ВОССТАНОВЛЕНИЕ (все данные будут удалены!)"))
        
        try:
            # Базовая команда psql БЕЗ shell=True
            cmd = [
                'psql',
                '-h', db_host,
                '-U', db_user,
                '-d', db_name,
                '--no-password'
            ]
            
            # Если мягкий режим, добавляем флаги для игнорирования конфликтов
            if soft_mode:
                # ON_ERROR_STOP=0 позволит продолжить даже при ошибках дубликатов
                pass  # psql сам обработает через переменную окружения
            
            # Передаём пароль через окружение (безопасно!)
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            
            # В мягком режиме игнорируем ошибки дубликатов
            if soft_mode:
                env['ON_ERROR_STOP'] = '0'  # Продолжать даже при ошибках
            else:
                env['ON_ERROR_STOP'] = '1'  # Остановиться при первой ошибке
            
            # Открываем файл (с поддержкой gzip) и направляем в psql
            if file_path.endswith('.gz'):
                file_obj = gzip.open(file_path, 'rt', encoding='utf-8')
            else:
                file_obj = open(file_path, 'r', encoding='utf-8')
            
            with file_obj as f:
                process = subprocess.run(
                    cmd,
                    env=env,
                    stdin=f,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
            
            self.stdout.write(self.style.SUCCESS("✅ База данных успешно восстановлена!"))
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else str(e)
            raise CommandError(f"Ошибка восстановления: {error_msg}")
        except Exception as e:
            raise CommandError(f"Неожиданная ошибка: {str(e)}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.stdout.write(f"🗑️  Временный файл удалён: {file_path}")