import os
import subprocess
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Восстанавливает БД из SQL дампа'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к файлу .sql или .sql.gz')

    def handle(self, *args, **options):
        file_path = options['file_path']
        if not os.path.exists(file_path):
            raise CommandError(f"Файл не найден: {file_path}")

        db_name = os.environ.get('DB_NAME', 'mydb')
        db_user = os.environ.get('DB_USER', 'myuser')

        self.stdout.write("⚠️  Начинается полное восстановление БД...")
        
        try:
            # Определяем команду в зависимости от сжатия
            if file_path.endswith('.gz'):
                cmd = f"zcat {file_path} | PGPASSWORD={os.environ.get('DB_PASSWORD')} psql -h db -U {db_user} -d {db_name}"
            else:
                cmd = f"PGPASSWORD={os.environ.get('DB_PASSWORD')} psql -h db -U {db_user} -d {db_name} < {file_path}"
            
            # Выполняем в оболочке
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            self.stdout.write(self.style.SUCCESS("✅ База данных успешно восстановлена!"))
            
        except subprocess.CalledProcessError as e:
            raise CommandError(f"Ошибка восстановления: {e.stderr}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)