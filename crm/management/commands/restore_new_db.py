import os
import subprocess
import gzip
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

class Command(BaseCommand):
    help = 'Восстанавливает БД из SQL дампа и синхронизирует счетчики ID'

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
        
        try:
            cmd = [
                'psql', '-h', db_host, '-U', db_user, '-d', db_name, '--no-password'
            ]
            
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            env['ON_ERROR_STOP'] = '1'
            
            if file_path.endswith('.gz'):
                file_obj = gzip.open(file_path, 'rt', encoding='utf-8')
            else:
                file_obj = open(file_path, 'r', encoding='utf-8')
            
            with file_obj as f:
                subprocess.run(
                    cmd, env=env, stdin=f,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
                )
            
            self.stdout.write(self.style.SUCCESS("✅ База данных восстановлена!"))
            
            # 🔥 НОВОЕ: Синхронизируем счетчики ID после восстановления
            self.stdout.write(self.style.WARNING("🔄 Синхронизируем счетчики ID (Sequences)..."))
            self._reset_sequences()
            self.stdout.write(self.style.SUCCESS("✅ Счетчики ID успешно синхронизированы!"))
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else str(e)
            raise CommandError(f"Ошибка восстановления: {error_msg}")
        except Exception as e:
            raise CommandError(f"Неожиданная ошибка: {str(e)}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    def _reset_sequences(self):
        """Сбрасывает все sequence в public схеме на максимальный id в соответствующих таблицах"""
        with connection.cursor() as cursor:
            # Находим все последовательности, связанные с таблицами в схеме public
            cursor.execute("""
                SELECT sequencename, tablename 
                FROM pg_sequences 
                WHERE schemaname = 'public' AND sequencename LIKE '%_id_seq';
            """)
            sequences = cursor.fetchall()
            
            for seq_name, table_name in sequences:
                try:
                    # Устанавливаем значение sequence равным max(id) в таблице
                    # coalesce(max(id), 1) защитит от ошибок на пустых таблицах
                    cursor.execute(f"""
                        SELECT setval('{seq_name}', coalesce(max(id), 1), max(id) IS NOT null) 
                        FROM {table_name};
                    """)
                except Exception:
                    # Если в таблице нет колонки 'id' или она называется иначе, просто пропускаем
                    pass