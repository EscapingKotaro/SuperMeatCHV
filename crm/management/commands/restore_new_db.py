import json
import gzip
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import transaction, connection
from django.core import serializers

class Command(BaseCommand):
    help = 'Загружает данные из JSON-дампа, обновляя существующие записи'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к .json или .json.gz')

    def handle(self, *args, **options):
        file_path = options['file_path']
        self.stdout.write(f"📂 Читаю файл: {file_path}")

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
            raise CommandError("Ожидался список объектов в JSON")

        self.stdout.write(f"📦 Найдено объектов: {len(data)}")

        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []

        # 🔥 Отключаем сигналы на время импорта, чтобы не было мусора
        from django.db.models.signals import post_save, post_delete
        from crm.models import (
            reconcile_confirmed_trial,
            refresh_newcomer_payment_after_delete,
            Attendance, Newcomer, Payment,
        )
        post_save.disconnect(reconcile_confirmed_trial, sender=Attendance)
        post_save.disconnect(reconcile_confirmed_trial, sender=Newcomer)
        post_save.disconnect(refresh_newcomer_payment_after_delete, sender=Payment)

        try:
            with transaction.atomic():
                for idx, item in enumerate(data, 1):
                    try:
                        model_path = item['model']
                        pk = item['pk']
                        fields = item.get('fields', {})

                        app_label, model_name = model_path.split('.')
                        Model = apps.get_model(app_label, model_name)

                        # Разделяем обычные поля и M2M
                        m2m_fields = {}
                        regular_fields = {}
                        for field_name, value in fields.items():
                            try:
                                field = Model._meta.get_field(field_name)
                                if field.many_to_many or field.one_to_many:
                                    m2m_fields[field_name] = value
                                else:
                                    regular_fields[field_name] = value
                            except Exception:
                                continue

                        obj, created = Model.objects.update_or_create(
                            pk=pk,
                            defaults=regular_fields,
                        )

                        # M2M устанавливаем после создания
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

            # 🔥 Синхронизируем sequence (счётчики ID)
            self.stdout.write("🔄 Синхронизирую счётчики ID...")
            self._reset_sequences()

        finally:
            # Возвращаем сигналы обратно
            post_save.connect(reconcile_confirmed_trial, sender=Attendance)
            post_save.connect(reconcile_confirmed_trial, sender=Newcomer)
            post_save.connect(refresh_newcomer_payment_after_delete, sender=Payment)

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
        """Сбрасывает sequence на max(id) в каждой таблице"""
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