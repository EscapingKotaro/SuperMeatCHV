import json
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import transaction

class Command(BaseCommand):
    help = 'Загружает данные из JSON дампа, обновляя существующие записи'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к JSON файлу')

    def handle(self, *args, **options):
        file_path = options['file_path']
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.stdout.write(f"📦 Загружено {len(data)} записей из дампа")
            
            created_count = 0
            updated_count = 0
            errors = []
            
            # Загружаем в том же порядке, как в дампе (dumpdata уже отсортировал зависимости)
            with transaction.atomic():
                for item in data:
                    try:
                        model_path = item['model']
                        pk = item['pk']
                        fields = item['fields']
                        
                        app_label, model_name = model_path.split('.')
                        Model = apps.get_model(app_label, model_name)
                        
                        # Разделяем M2M поля и обычные
                        m2m_fields = {}
                        regular_fields = {}
                        
                        for field_name, value in fields.items():
                            try:
                                field = Model._meta.get_field(field_name)
                                if field.many_to_many:
                                    m2m_fields[field_name] = value
                                else:
                                    regular_fields[field_name] = value
                            except Exception:
                                # Если поле не найдено (например, удалено из модели), пропускаем
                                continue
                        
                        # Создаём/обновляем объект по первичному ключу
                        obj, created = Model.objects.update_or_create(
                            pk=pk,
                            defaults=regular_fields
                        )
                        
                        # Устанавливаем M2M связи
                        for field_name, value in m2m_fields.items():
                            try:
                                getattr(obj, field_name).set(value)
                            except Exception as e:
                                errors.append(f"M2M error for {model_path}#{pk}.{field_name}: {e}")
                        
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                            
                    except Exception as e:
                        errors.append(f"{item.get('model', 'unknown')}#{item.get('pk', '?')}: {e}")
            
            self.stdout.write(self.style.SUCCESS(
                f"✅ Загрузка завершена!\n"
                f"   Создано: {created_count}\n"
                f"   Обновлено: {updated_count}\n"
                f"   Ошибок: {len(errors)}"
            ))
            
            if errors:
                self.stdout.write(self.style.WARNING("⚠️  Первые 10 ошибок:"))
                for error in errors[:10]:
                    self.stdout.write(f"   • {error}")
                    
        except Exception as e:
            raise CommandError(f"Ошибка загрузки: {e}")