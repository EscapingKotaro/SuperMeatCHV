import json
import gzip
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import transaction, connection

class Command(BaseCommand):
    help = 'Загружает данные из JSON-дампа, обновляя существующие записи'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к .json или .json.gz')

    def handle(self, *args, **options):
        file_path = options['file_path']
        self.stdout.write(f"📂 Читаю файл: {file_path}")

        import os
        file_size = os.path.getsize(file_path)
        self.stdout.write(f"📏 Размер файла: {file_size} байт")

        if file_size == 0:
            raise CommandError("Файл пустой!")

        try:
            if file_path.endswith('.gz'):
                with gzip.open(file_path, 'rt', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
        except Exception as e:
            raise CommandError(f"Не удалось прочитать файл: {e}")

        if not isinstance(data, list):
            raise CommandError(f"Ожидался список объектов, но получили: {type(data)}")

        self.stdout.write(f"📦 Найдено объектов в дампе: {len(data)}")

        if len(data) == 0:
            self.stdout.write(self.style.WARNING("⚠️  Дамп пустой! Нечего загружать."))
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []

        with transaction.atomic():
            for idx, item in enumerate(data, 1):
                try:
                    model_path = item['model']
                    pk = item['pk']
                    fields = item.get('fields', {})

                    app_label, model_name = model_path.split('.')
                    Model = apps.get_model(app_label, model_name)

                    m2m_fields = {}
                    regular_fields = {}
                    
                    for field_name, value in fields.items():
                        try:
                            field = Model._meta.get_field(field_name)
                            
                            # 🔥 ИСПРАВЛЕНИЕ: Обработка Foreign Key
                            if field.many_to_many:
                                m2m_fields[field_name] = value
                            elif field.is_relation and not field.many_to_many:
                                # Если это ForeignKey или OneToOne, передаем значение как _id
                                if value is not None:
                                    regular_fields[f"{field_name}_id"] = value
                                else:
                                    regular_fields[field_name] = None
                            else:
                                regular_fields[field_name] = value
                        except Exception:
                            # Поля, которых нет в новой модели, просто игнорируем
                            continue

                    obj, created = Model.objects.update_or_create(
                        pk=pk,
                        defaults=regular_fields,
                    )

                    for field_name, value in m2m_fields.items():
                        try:
                            getattr(obj, field_name).set(value or [])
                        except Exception as e:
                            errors.append(f"M2M {model_path}#{pk}.{field_name}: {e}")

                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

                    if idx % 500 == 0:
                        self.stdout.write(f"   ... обработано {idx}/{len(data)}")

                except Exception as e:
                    errors.append(f"{item.get('model')}#{item.get('pk')}: {e}")
                    skipped_count += 1

            self.stdout.write("🔄 Синхронизирую счётчики ID...")
            self._reset_sequences()

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Готово!\n"
            f"   Создано: {created_count}\n"
            f"   Обновлено: {updated_count}\n"
            f"   Пропущено с ошибками: {skipped_count}"
        ))

        if errors:
            self.stdout.write(self.style.WARNING(f"\n⚠️  Ошибок: {len(errors)}. Первые 15:"))
            for err in errors[:15]:
                self.stdout.write(f"   • {err}")

    def _reset_sequences(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sequencename, 
                       replace(sequencename, '_id_seq', '') as table_name
                FROM pg_sequences 
                WHERE schemaname = 'public' 
                  AND sequencename LIKE '%_id_seq';
            """)
            for seq_name, table_name in cursor.fetchall():
                try:
                    cursor.execute(f"""
                        SELECT setval(%s, coalesce((SELECT max(id) FROM {table_name}), 1), 
                                       (SELECT max(id) FROM {table_name}) IS NOT NULL)
                    """, [seq_name])
                except Exception:
                    pass