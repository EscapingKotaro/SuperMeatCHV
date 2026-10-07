import sqlite3
import os
import re
import traceback
from datetime import datetime, date as dt_date, time as dt_time
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from crm.models import (
    Trainer, Group, Child, ChildGroupMembership, 
    Tariff, Subscription, Attendance, Payment, ScheduleSlot,
    reconcile_confirmed_trial, refresh_newcomer_payment_after_delete, Newcomer
)

class Command(BaseCommand):
    help = 'Миграция данных из старой SQLite базы в новую (безопасный режим)'

    def add_arguments(self, parser):
        parser.add_argument('db_path', type=str, help='Путь к файлу старой базы данных')

    def handle(self, *args, **options):
        db_path = options['db_path']
        self.stdout.write(f"🔍 Подключение к старой базе: {db_path}")
        
        try:
            old_conn = sqlite3.connect(db_path)
            old_conn.row_factory = sqlite3.Row
            old_cursor = old_conn.cursor()
        except Exception as e:
            raise CommandError(f"Не удалось открыть базу: {e}")

        # 🔥 ОТКЛЮЧАЕМ СИГНАЛЫ на время импорта, чтобы избежать побочных эффектов
        post_save.disconnect(reconcile_confirmed_trial, sender=Attendance)
        post_save.disconnect(reconcile_confirmed_trial, sender=Newcomer)
        post_delete.disconnect(refresh_newcomer_payment_after_delete, sender=Payment)

        trainer_map = {}
        group_map = {}
        child_map = {}
        tariff_map = {}

        try:
            with transaction.atomic():
                # ==========================================
                # ЭТАП 1: Тренеры
                # ==========================================
                self.stdout.write("🔄 Этап 1: Перенос Тренеров")
                old_cursor.execute("SELECT teacherId, teacherName FROM Teacher")
                for row in old_cursor.fetchall():
                    name = row['teacherName'] or f"Тренер_{row['teacherId']}"
                    if 'Pass:' in name:
                        name = name.split('Pass:')[0].strip() or f"Тренер_{row['teacherId']}"
                    
                    trainer, _ = Trainer.objects.update_or_create(
                        id=int(row['teacherId']),
                        defaults={'full_name': name[:200], 'phone': '', 'is_active': True}
                    )
                    trainer_map[int(row['teacherId'])] = trainer.id
                self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено тренеров: {len(trainer_map)}"))

                # ==========================================
                # ЭТАП 2: Группы + Графики
                # ==========================================
                self.stdout.write("🔄 Этап 2: Перенос Групп и Графиков")
                old_cursor.execute("""
                    SELECT g.ClGrTypeId, g.ClGrTypeName, g.ClGrTypeTeacherId, g.ClGrTypeSchedule, d.DisciplineSingleVisitPrice 
                    FROM ClientGroupType g
                    LEFT JOIN DisciplineType d ON g.ClGrTypeDisciplineID = d.DisciplineId
                """)
                for row in old_cursor.fetchall():
                    trainer_id = trainer_map.get(int(row['ClGrTypeTeacherId']))
                    if not trainer_id:
                        trainer_id = Trainer.objects.first().id if Trainer.objects.exists() else Trainer.objects.create(full_name="Неизвестный").id
                    
                    group, _ = Group.objects.update_or_create(
                        id=int(row['ClGrTypeId']),
                        defaults={
                            'name': (row['ClGrTypeName'] or f"Группа_{row['ClGrTypeId']}")[:100],
                            'trainer_id': trainer_id,
                            'is_active': True,
                            'single_session_price': Decimal(row['DisciplineSingleVisitPrice'] or 0),
                            'salary_rate': Decimal(300),
                        }
                    )
                    group_map[int(row['ClGrTypeId'])] = group.id

                    schedule_str = (row['ClGrTypeSchedule'] or '').strip()
                    if schedule_str:
                        start_time = dt_time(0, 0)
                        time_match = re.search(r'(\d{1,2})[.:](\d{2})', row['ClGrTypeName'] or '')
                        if time_match:
                            h, m = int(time_match.group(1)), int(time_match.group(2))
                            if 0 <= h <= 23 and 0 <= m <= 59:
                                start_time = dt_time(h, m)

                        for ch in schedule_str:
                            if ch.isdigit():
                                old_day = int(ch)
                                if 1 <= old_day <= 7:
                                    ScheduleSlot.objects.get_or_create(
                                        group_id=group.id,
                                        weekday=old_day - 1,
                                        start_time=start_time,
                                        defaults={'duration_minutes': 60}
                                    )
                self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено групп: {len(group_map)}"))

                # Временная группа
                temp_trainer = Trainer.objects.first() or Trainer.objects.create(full_name="Временный")
                temp_group, _ = Group.objects.get_or_create(
                    name="⚠️ Импорт (временная)",
                    defaults={'trainer_id': temp_trainer.id, 'is_active': False, 'single_session_price': 0, 'salary_rate': 0}
                )

                # ==========================================
                # ЭТАП 3: Дети
                # ==========================================
                self.stdout.write("🔄 Этап 3: Перенос Детей")
                old_cursor.execute("SELECT * FROM Client")

                for row in old_cursor.fetchall():
                    try:
                        c_id = int(row['ClientID'])
                    except (ValueError, TypeError):
                        continue

                    last_name = (row['ClientSurname'] or "").strip()
                    first_name = (row['ClientName'] or "").strip()
                    patronymic = (row['ClientFatherName'] or "").strip()

                    if not last_name and first_name:
                        parts = first_name.split()
                        if len(parts) >= 2:
                            last_name = parts[0]
                            first_name = parts[1]

                    birth_date = None
                    birth_year = 2010
                    if row['ClientBirthday'] and str(row['ClientBirthday']) != '1899-12-30':
                        try:
                            birth_date = datetime.strptime(str(row['ClientBirthday']), "%Y-%m-%d").date()
                            birth_year = birth_date.year
                        except ValueError:
                            pass

                    child, _ = Child.objects.update_or_create(
                        id=c_id,
                        defaults={
                            'first_name': (first_name or "Без имени")[:100],
                            'last_name': (last_name or "Без фамилии")[:100],
                            'patronymic': patronymic[:100],
                            'birth_year': birth_year,
                            'birth_date': birth_date,
                            'address': (str(row['ClientAddress']) or "")[:255],
                            'parent_phone': (str(row['ClientPhone']) or "")[:20],
                            'group_id': temp_group.id,
                            'status': 'active',
                            'discount_percent': 10 if row['ClientIsHaveDiscount'] else 0,
                            'note': (str(row['ClientComment']) or "")[:500],
                        }
                    )
                    child_map[c_id] = child.id
                self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено детей: {len(child_map)}"))
                
                # ==========================================
                # ЭТАП 4: Членства
                # ==========================================
                self.stdout.write("🔄 Этап 4: Перенос Членства в группах")
                ChildGroupMembership.objects.all().delete()
                self.stdout.write("   🗑️ Очищены временные членства")

                old_cursor.execute("SELECT ClGrId, ClGrClientId, ClGrClGrTypeId FROM ClientGroup")
                child_groups = {}
                for row in old_cursor.fetchall():
                    try:
                        c_id = int(row['ClGrClientId'])
                        g_id = int(row['ClGrClGrTypeId'])
                        clgr_id = int(row['ClGrId'])
                    except (ValueError, TypeError):
                        continue
                    
                    child_id = child_map.get(c_id)
                    group_id = group_map.get(g_id)
                    
                    if child_id and group_id:
                        if child_id not in child_groups:
                            child_groups[child_id] = []
                        child_groups[child_id].append({'group_id': group_id, 'clgr_id': clgr_id})

                count = 0
                for child_id, groups in child_groups.items():
                    try:
                        # 🔥 Явная проверка перед любыми действиями
                        if not Child.objects.filter(id=child_id).exists():
                            self.stdout.write(self.style.WARNING(f"   ⚠️ Ребёнок id={child_id} не найден в БД, пропускаем"))
                            continue

                        groups.sort(key=lambda x: x['clgr_id'], reverse=True)
                        primary_group_id = groups[0]['group_id']
                        
                        for idx, group_data in enumerate(groups):
                            ChildGroupMembership.objects.create(
                                child_id=child_id,
                                group_id=group_data['group_id'],
                                is_primary=(idx == 0),
                                joined_at=dt_date.today(),
                                archived_at=None if (idx == 0) else dt_date.today(),
                                requires_subscription=True,
                            )
                            count += 1
                        
                        Child.objects.filter(id=child_id).update(group_id=primary_group_id)
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"   ❌ Ошибка на child_id={child_id}: {e}"))
                        raise

                temp_group.delete()
                self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено связей: {count}"))

                # ==========================================
                # ЭТАП 5: Тарифы
                # ==========================================
                self.stdout.write("🔄 Этап 5: Перенос Тарифов")
                old_cursor.execute("SELECT * FROM ClientSubscriptionType")
                for row in old_cursor.fetchall():
                    try:
                        t_id = int(row['ClSubscrTypeId'])
                    except (ValueError, TypeError):
                        continue
                    Tariff.objects.update_or_create(
                        id=t_id,
                        defaults={
                            'name': (row['ClSubscrTypeName'] or f"Тариф_{t_id}")[:120],
                            'price': Decimal(row['ClSubscrTypePrice'] or 0),
                            'sessions_total': row['ClSubscrTypeTotalLessons'] or 8,
                            'duration_days': row['ClSubscrTypeActiveDays'] or 30,
                            'is_active': bool(row['ClSubscrTypeIsActive']),
                        }
                    )
                    tariff_map[t_id] = t_id
                self.stdout.write(self.style.SUCCESS(f"   ✅ Перенесено тарифов: {len(tariff_map)}"))

                # ==========================================
                # ЭТАП 6: Абонементы
                # ==========================================
                self.stdout.write("🔄 Этап 6: Перенос Абонементов")
                old_cursor.execute("SELECT ClSubscrId, ClSubscrClientID, ClSubscrClSubscrTypeId, ClSubscrDateStart, ClSubscrDateFinish, ClSubscrAvailLessons FROM ClientSubscription")
                for row in old_cursor.fetchall():
                    try:
                        sub_id = int(row['ClSubscrId'])
                        c_id = int(row['ClSubscrClientID'])
                        t_id = int(row['ClSubscrClSubscrTypeId'])
                    except (ValueError, TypeError):
                        continue

                    child_id = child_map.get(c_id)
                    if not child_id:
                        continue
                    
                    child_obj = Child.objects.filter(id=child_id).first()
                    if not child_obj:
                        continue

                    start_date = row['ClSubscrDateStart'] or dt_date.today()
                    end_date = row['ClSubscrDateFinish'] or dt_date.today()

                    Subscription.objects.update_or_create(
                        id=sub_id,
                        defaults={
                            'child_id': child_id,
                            'group_id': child_obj.group_id,
                            'tariff_id': tariff_map.get(t_id),
                            'start_date': start_date,
                            'end_date': end_date,
                            'sessions_total': row['ClSubscrAvailLessons'] or 8,
                            'price': Decimal(Tariff.objects.get(id=tariff_map.get(t_id)).price if tariff_map.get(t_id) else 0),
                            'is_active': True,
                        }
                    )
                self.stdout.write(self.style.SUCCESS("   ✅ Абонементы перенесены"))

                # ==========================================
                # ЭТАП 7: Посещения
                # ==========================================
                self.stdout.write("🔄 Этап 7: Перенос Посещений")
                old_cursor.execute("""
                    SELECT v.ClVisitId, v.ClVisitDate, v.ClVisitClientSubscriptionId, s.ClSubscrClientID
                    FROM ClientVisit v
                    LEFT JOIN ClientSubscription s ON v.ClVisitClientSubscriptionId = s.ClSubscrId
                """)
                for row in old_cursor.fetchall():
                    if not row['ClSubscrClientID'] or not row['ClVisitDate']:
                        continue
                        
                    try:
                        visit_id = int(row['ClVisitId'])
                        c_id = int(row['ClSubscrClientID'])
                    except (ValueError, TypeError):
                        continue

                    child_id = child_map.get(c_id)
                    if not child_id:
                        continue

                    child_obj = Child.objects.filter(id=child_id).first()
                    if not child_obj:
                        continue
                    
                    Attendance.objects.update_or_create(
                        id=visit_id,
                        defaults={
                            'child_id': child_id,
                            'date': row['ClVisitDate'],
                            'group_snapshot_id': child_obj.group_id,
                            'status': 'present',
                            'charge_amount': Decimal(0),
                        }
                    )
                self.stdout.write(self.style.SUCCESS("   ✅ Посещения перенесены"))

                # ==========================================
                # ЭТАП 8: Оплаты
                # ==========================================
                self.stdout.write("🔄 Этап 8: Перенос Оплат")
                old_cursor.execute("SELECT CashFlowID, CashFlowIncome, CashFlowDate, CashFlowClientID, CashFlowComment FROM CashFlow WHERE CashFlowIncome > 0 AND CashFlowClientID > 0")
                for row in old_cursor.fetchall():
                    try:
                        cf_id = int(row['CashFlowID'])
                        c_id = int(row['CashFlowClientID'])
                    except (ValueError, TypeError):
                        continue

                    child_id = child_map.get(c_id)
                    if not child_id:
                        continue
                    
                    Payment.objects.update_or_create(
                        id=cf_id,
                        defaults={
                            'child_id': child_id,
                            'amount': Decimal(row['CashFlowIncome']),
                            'date': row['CashFlowDate'] or dt_date.today(),
                            'operation_kind': 'payment',
                            'reason': (str(row['CashFlowComment']) or "Импорт")[:500],
                        }
                    )
                self.stdout.write(self.style.SUCCESS("   ✅ Оплаты перенесены"))

            self.stdout.write(self.style.SUCCESS("🎉 Миграция успешно завершена!"))
        
        except Exception as e:
            # 🔥 ПЕЧАТАЕМ ПОЛНЫЙ СТЕК ВЫЗОВА, ЧТОБЫ НАЙТИ ВИРУСА
            self.stdout.write(self.style.ERROR("❌ КРИТИЧЕСКАЯ ОШИБКА МИГРАЦИИ:"))
            self.stdout.write(self.style.ERROR(traceback.format_exc()))
            raise CommandError(f"Ошибка миграции: {e}")
        finally:
            # 🔥 ВОЗВРАЩАЕМ СИГНАЛЫ ОБРАТНО, ЧТОБЫ CRM РАБОТАЛА НОРМАЛЬНО
            post_save.connect(reconcile_confirmed_trial, sender=Attendance)
            post_save.connect(reconcile_confirmed_trial, sender=Newcomer)
            post_delete.connect(refresh_newcomer_payment_after_delete, sender=Payment)
            old_conn.close()