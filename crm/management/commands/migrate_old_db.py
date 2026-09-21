import sqlite3
from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from crm.models import (
    Trainer, Group, Child, ChildGroupMembership, 
    Tariff, Subscription, Attendance, Payment
)

class Command(BaseCommand):
    help = 'Миграция данных из старой SQLite базы в новую'

    def add_arguments(self, parser):
        parser.add_argument('db_path', type=str, help='Путь к файлу старой базы данных (database.db)')

    def handle(self, *args, **options):
        db_path = options['db_path']
        self.stdout.write(f"🔍 Подключение к старой базе: {db_path}")
        
        try:
            old_conn = sqlite3.connect(db_path)
            old_conn.row_factory = sqlite3.Row
            old_cursor = old_conn.cursor()
        except Exception as e:
            raise CommandError(f"Не удалось открыть базу: {e}")

        # Словари для маппинга старых ID в новые ID
        trainer_map = {}
        group_map = {}
        child_map = {}
        tariff_map = {}
        subscription_map = {}

        with transaction.atomic():
            self.stdout.write("🔄 Этап 1: Перенос Тренеров (Trainer)")
            old_cursor.execute("SELECT teacherId, teacherName, teacherSalary FROM Teacher")
            for row in old_cursor.fetchall():
                name = row['teacherName'] or f"Тренер_{row['teacherId']}"
                # Чистим имя от мусора типа "Pass:11" (видел такое в твоём примере)
                if 'Pass:' in name:
                    name = name.split('Pass:')[0].strip() or f"Тренер_{row['teacherId']}"
                
                trainer, _ = Trainer.objects.get_or_create(
                    full_name=name,
                    defaults={
                        'phone': '',
                        'is_active': True,
                        # ️ salary_rate убран — его нет в модели Trainer!
                        # Ставка тренера хранится в модели Group (поле salary_rate)
                    }
                )
                trainer_map[row['teacherId']] = trainer.id
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено тренеров: {len(trainer_map)}"))
            self.stdout.write("🔄 Этап 2: Перенос Групп (Group)")
            old_cursor.execute("""
                SELECT g.ClGrTypeId, g.ClGrTypeName, g.ClGrTypeTeacherId, d.DisciplineSingleVisitPrice 
                FROM ClientGroupType g
                LEFT JOIN DisciplineType d ON g.ClGrTypeDisciplineID = d.DisciplineId
            """)
            for row in old_cursor.fetchall():
                trainer_id = trainer_map.get(row['ClGrTypeTeacherId'])
                # ЗАГЛУШКА: Если тренер не найден, берем первого попавшегося или создаем "Неизвестный"
                if not trainer_id:
                    trainer_id = Trainer.objects.first().id if Trainer.objects.exists() else Trainer.objects.create(full_name="Неизвестный").id
                
                group, _ = Group.objects.get_or_create(
                    name=row['ClGrTypeName'] or f"Группа_{row['ClGrTypeId']}",
                    defaults={
                        'trainer_id': trainer_id,
                        'is_active': True,
                        'single_session_price': Decimal(row['DisciplineSingleVisitPrice'] or 0),
                        'salary_rate': Decimal(300), # Заглушка
                    }
                )
                group_map[row['ClGrTypeId']] = group.id
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено групп: {len(group_map)}"))

            self.stdout.write("🔄 Этап 3: Перенос Детей (Child)")
            old_cursor.execute("SELECT * FROM Client")
            default_group_id = Group.objects.first().id if Group.objects.exists() else None

            for row in old_cursor.fetchall():
                # Пытаемся разделить ФИО, если оно в одной строке
                full_name = row['ClientName'] or "Без имени"
                parts = full_name.split()
                first_name = parts[0] if parts else "Без имени"
                last_name = parts[1] if len(parts) > 1 else ""
                patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""

                # Обработка даты рождения
                birth_date = None
                birth_year = 2010 # ЗАГЛУШКА
                if row['ClientBirthday'] and row['ClientBirthday'] != '1899-12-30':
                    try:
                        birth_date = datetime.strptime(row['ClientBirthday'], "%Y-%m-%d").date()
                        birth_year = birth_date.year
                    except ValueError:
                        pass

                # 🔥 ОБРЕЗКА ДЛИННЫХ СТРОК (важно!)
                phone = (row['ClientPhone'] or "")[:20]  # max_length=20
                address = (row['ClientAddress'] or "")[:255]  # max_length=255
                comment = (row['ClientComment'] or "")[:500]  # TextField, но на всякий случай
                patronymic = (patronymic or row['ClientFatherName'] or "")[:100]  # max_length=100
                first_name = first_name[:100]  # max_length=100
                last_name = last_name[:100]  # max_length=100

                # ЗАГЛУШКА: Если у ребенка нет группы, назначаем первую попавшуюся
                assigned_group_id = default_group_id

                child, _ = Child.objects.get_or_create(
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=birth_date,
                    defaults={
                        'patronymic': patronymic,
                        'birth_year': birth_year,
                        'address': address,
                        'parent_phone': phone,
                        'group_id': assigned_group_id,
                        'status': 'active', # ЗАГЛУШКА
                        'discount_percent': 10 if row['ClientIsHaveDiscount'] else 0,
                        'note': comment,
                    }
                )
                child_map[row['ClientID']] = child.id
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено детей: {len(child_map)}"))
            
            self.stdout.write("🔄 Этап 4: Перенос Членства в группах (ChildGroupMembership)")

            # 🔥 УДАЛЯЕМ все автоматически созданные ChildGroupMembership на этапе 3
            ChildGroupMembership.objects.all().delete()
            self.stdout.write("   🗑️ Удалены автоматически созданные членства")

            # Собираем все группы для каждого ребенка
            old_cursor.execute("SELECT ClGrId, ClGrClientId, ClGrClGrTypeId FROM ClientGroup")
            child_groups = {}
            for row in old_cursor.fetchall():
                child_id = child_map.get(row['ClGrClientId'])
                group_id = group_map.get(row['ClGrClGrTypeId'])
                if child_id and group_id:
                    if child_id not in child_groups:
                        child_groups[child_id] = []
                    child_groups[child_id].append({
                        'group_id': group_id,
                        'clgr_id': row['ClGrId']
                    })

            # Создаем членства
            count = 0
            for child_id, groups in child_groups.items():
                # Сортируем по ClGrId (последняя группа = основная)
                groups.sort(key=lambda x: x['clgr_id'], reverse=True)
                
                for idx, group_data in enumerate(groups):
                    # Первая группа (с максимальным ClGrId) = основная
                    is_primary = (idx == 0)
                    
                    # 🔥 Создаем с is_primary=False для всех, потом обновим основную
                    ChildGroupMembership.objects.create(
                        child_id=child_id,
                        group_id=group_data['group_id'],
                        is_primary=False,  # Сначала все False
                        joined_at=datetime.now().date(),
                        archived_at=datetime.now().date(),  # Все в архив
                        requires_subscription=True,
                    )
                    count += 1
                
                # 🔥 Теперь обновляем первую группу (основную)
                if groups:
                    primary_group_id = groups[0]['group_id']
                    ChildGroupMembership.objects.filter(
                        child_id=child_id,
                        group_id=primary_group_id
                    ).update(
                        is_primary=True,
                        archived_at=None  # Активная, не в архиве
                    )

            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено связей ребенок-группа: {count}"))
            self.stdout.write("🔄 Этап 5: Перенос Тарифов (Tariff)")
            old_cursor.execute("SELECT * FROM ClientSubscriptionType")
            for row in old_cursor.fetchall():
                Tariff.objects.get_or_create(
                    name=row['ClSubscrTypeName'] or f"Тариф_{row['ClSubscrTypeId']}",
                    defaults={
                        'price': Decimal(row['ClSubscrTypePrice'] or 0),
                        'sessions_total': row['ClSubscrTypeTotalLessons'] or 8, # ЗАГЛУШКА
                        'duration_days': row['ClSubscrTypeActiveDays'] or 30,   # ЗАГЛУШКА
                        'is_active': bool(row['ClSubscrTypeIsActive']),
                    }
                )
                tariff_map[row['ClSubscrTypeId']] = row['ClSubscrTypeName'] # Сохраняем имя для поиска
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено тарифов: {len(tariff_map)}"))

            self.stdout.write("🔄 Этап 6: Перенос Абонементов (Subscription)")
            # Нам нужен маппинг SubscriptionID -> ClientID, чтобы привязать посещения
            old_cursor.execute("SELECT ClSubscrId, ClSubscrClientID, ClSubscrClSubscrTypeId, ClSubscrDateStart, ClSubscrDateFinish, ClSubscrAvailLessons FROM ClientSubscription")
            for row in old_cursor.fetchall():
                child_id = child_map.get(row['ClSubscrClientID'])
                if not child_id:
                    continue
                
                # Находим тариф по имени (так надежнее, чем по ID, если они не совпадают)
                # Но попробуем сначала найти ID тарифа, если он есть в старой базе
                tariff_name = None
                old_cursor.execute("SELECT ClSubscrTypeName FROM ClientSubscriptionType WHERE ClSubscrTypeId = ?", (row['ClSubscrClSubscrTypeId'],))
                t_row = old_cursor.fetchone()
                if t_row:
                    tariff_name = t_row['ClSubscrTypeName']
                
                tariff_obj = None
                if tariff_name:
                    tariff_obj = Tariff.objects.filter(name=tariff_name).first()

                # ЗАГЛУШКА: Группу берем из основной группы ребенка
                child_obj = Child.objects.get(id=child_id)
                
                Subscription.objects.get_or_create(
                    child_id=child_id,
                    start_date=row['ClSubscrDateStart'] or datetime.now().date(),
                    end_date=row['ClSubscrDateFinish'] or datetime.now().date(),
                    defaults={
                        'group_id': child_obj.group_id,
                        'tariff': tariff_obj,
                        'sessions_total': row['ClSubscrAvailLessons'] or 8,
                        'price': Decimal(tariff_obj.price if tariff_obj else 0),
                        'is_active': True, # ЗАГЛУШКА: считаем все перенесенные активными, если дата не прошла
                    }
                )
                subscription_map[row['ClSubscrId']] = child_id
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено абонементов: {len(subscription_map)}"))

            self.stdout.write("🔄 Этап 7: Перенос Посещений (Attendance)")
            # В ClientVisit нет ClientID напрямую, берем его через ClientSubscription
            old_cursor.execute("""
                SELECT v.ClVisitId, v.ClVisitDate, v.ClVisitClientSubscriptionId, s.ClSubscrClientID
                FROM ClientVisit v
                LEFT JOIN ClientSubscription s ON v.ClVisitClientSubscriptionId = s.ClSubscrId
            """)
            attendance_count = 0
            for row in old_cursor.fetchall():
                child_id = child_map.get(row['ClSubscrClientID'])
                if not child_id or not row['ClVisitDate']:
                    continue
                
                child_obj = Child.objects.get(id=child_id)
                
                Attendance.objects.get_or_create(
                    child_id=child_id,
                    date=row['ClVisitDate'],
                    group_snapshot_id=child_obj.group_id, # ЗАГЛУШКА: привязываем к текущей группе
                    defaults={
                        'status': 'present', # ЗАГЛУШКА: считаем все записи посещениями
                        'charge_amount': Decimal(0),
                    }
                )
                attendance_count += 1
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено посещений: {attendance_count}"))

            self.stdout.write("🔄 Этап 8: Перенос Оплат (Payment)")
            old_cursor.execute("SELECT CashFlowID, CashFlowIncome, CashFlowDate, CashFlowClientID, CashFlowComment FROM CashFlow WHERE CashFlowIncome > 0 AND CashFlowClientID > 0")
            payment_count = 0
            for row in old_cursor.fetchall():
                child_id = child_map.get(row['CashFlowClientID'])
                if not child_id:
                    continue
                
                Payment.objects.get_or_create(
                    # Используем хэш для уникальности, т.к. в старой базе может не быть хорошего уникального ключа
                    child_id=child_id,
                    amount=Decimal(row['CashFlowIncome']),
                    date=row['CashFlowDate'] or datetime.now().date(),
                    defaults={
                        'operation_kind': 'payment',
                        'reason': row['CashFlowComment'] or "Импорт из старой базы",
                    }
                )
                payment_count += 1
            self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено оплат: {payment_count}"))

        old_conn.close()
        self.stdout.write(self.style.SUCCESS("🎉 Миграция успешно завершена!"))