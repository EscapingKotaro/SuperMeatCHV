import os
import subprocess
import gzip
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Полное восстановление БД из SQL дампа (все данные будут заменены!)'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к файлу .sql или .sql.gz')

    def handle(self, *args, **options):
        file_path = options['file_path']
        
        if not os.path.exists(file_path):
            raise CommandError(f"Файл не найден: {file_path}")

        db_name = os.environ.get('DB_NAME', 'mydb')
        db_user = os.environ.get('DB_USER', 'myuser')
        db_password = os.environ.get('DB_PASSWORD', '')
        db_host = os.environ.get('DB_HOST', 'db')

        self.stdout.write(self.style.WARNING("⚠️  Начинается ПОЛНОЕ восстановление БД..."))
        self.stdout.write(self.style.ERROR("🔥 Все текущие данные будут УДАЛЕНЫ и заменены!"))
        
        try:
            # Команда psql БЕЗ shell=True (безопасно для спецсимволов в пароле)
            cmd = [
                'psql',
                '-h', db_host,
                '-U', db_user,
                '-d', db_name,
                '--no-password'
            ]
            
            # Передаём пароль через окружение
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            env['ON_ERROR_STOP'] = '1'  # Остановиться при первой ошибке
            
            # Открываем файл (с поддержкой gzip)
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
            
            self.stdout.write(self.style.SUCCESS("✅ База данных полностью восстановлена!"))
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else str(e)
            raise CommandError(f"Ошибка восстановления: {error_msg}")
        except Exception as e:
            raise CommandError(f"Неожиданная ошибка: {str(e)}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.stdout.write(f"🗑️  Временный файл удалён: {file_path}")