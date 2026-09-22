import os
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Восстанавливает данные из старой SQLite базы'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к файлу старой базы')

    def handle(self, *args, **options):
        file_path = options['file_path']
        if not os.path.exists(file_path):
            raise CommandError(f"Файл не найден: {file_path}")
        
        self.stdout.write("🔄 Запуск миграции из старой базы...")
        try:
            # Вызываем наш старый скрипт, который мы уже написали
            call_command('migrate_old_db', file_path)
            self.stdout.write(self.style.SUCCESS("✅ Старая база успешно перенесена!"))
        except Exception as e:
            raise CommandError(f"Ошибка миграции: {e}")
        finally:
            # Удаляем временный файл после завершения
            if os.path.exists(file_path):
                os.remove(file_path)