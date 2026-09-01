from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm.models import (
    Apparatus,
    ApparatusScore,
    Attendance,
    Branch,
    Child,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    ManagerTask,
    Newcomer,
    Payment,
    RevenueTarget,
    Reminder,
    Role,
    SalaryPayout,
    ScheduleSlot,
    StaffProfile,
    Subscription,
    Tariff,
    Trainer,
)


class Command(BaseCommand):
    help = "Создаёт тестовые аккаунты и демонстрационные данные CRM"

    def handle(self, *args, **options):
        today = timezone.localdate()
        month = today.replace(day=1)
        user_model = get_user_model()
        users = {}
        account_data = [
            ("boss", "Сергей", "Андреев", Role.BOSS),
            ("senior", "Мария", "Кокорина", Role.SENIOR),
            ("admin", "Антон", "Соколов", Role.MANAGER),
        ]
        for username, first_name, last_name, role in account_data:
            user, _ = user_model.objects.update_or_create(
                username=username,
                defaults={"first_name": first_name, "last_name": last_name, "is_staff": True, "is_active": True},
            )
            user.set_password("Demo12345!")
            user.save()
            StaffProfile.objects.update_or_create(user=user, defaults={"role": role})
            users[username] = user

        branch, _ = Branch.objects.update_or_create(
            name="Люберцы", defaults={"address": "Люберцы", "is_active": True}
        )
        for username in ("admin", "senior"):
            profile = users[username].profile
            profile.branch = branch
            profile.shift_anchor = today if username == "admin" else today + timedelta(days=2)
            profile.save(update_fields=["branch", "shift_anchor"])

        trainer1, _ = Trainer.objects.update_or_create(full_name="Ольга Воронова", defaults={"phone": "+7 900 111-22-33"})
        trainer2, _ = Trainer.objects.update_or_create(full_name="Анна Миронова", defaults={"phone": "+7 900 222-33-44"})
        senior_group, _ = Group.objects.update_or_create(name="Старшая группа", defaults={"trainer": trainer1, "branch": branch, "single_session_price": Decimal("900")})
        junior_group, _ = Group.objects.update_or_create(name="Младшая группа", defaults={"trainer": trainer2, "branch": branch, "single_session_price": Decimal("800")})
        for group, hour in ((senior_group, 18), (junior_group, 16)):
            for weekday in (0, 2, 5):
                ScheduleSlot.objects.update_or_create(group=group, weekday=weekday, defaults={"start_time": time(hour, 0), "duration_minutes": 90})

        children_data = [
            ("Соколова", "Алиса", 2015, senior_group, Child.Status.ACTIVE, "Елена Соколова", "+7 912 345-67-89"),
            ("Кузнецова", "Мария", 2014, senior_group, Child.Status.ACTIVE, "Наталья Кузнецова", "+7 922 100-24-11"),
            ("Петрова", "Анна", 2016, junior_group, Child.Status.ACTIVE, "Ирина Петрова", "+7 999 120-44-31"),
            ("Егорова", "Варвара", 2016, junior_group, Child.Status.TRIAL, "Ольга Егорова", "+7 912 800-10-20"),
        ]
        children = []
        for last_name, first_name, birth_year, group, status, parent_name, phone in children_data:
            child, _ = Child.objects.update_or_create(
                last_name=last_name, first_name=first_name,
                defaults={"birth_year": birth_year, "group": group, "status": status, "parent_name": parent_name, "parent_phone": phone, "trial_from": today if status == Child.Status.TRIAL else None},
            )
            children.append(child)

        tariff, _ = Tariff.objects.update_or_create(
            name="8 занятий", defaults={"price": Decimal("5600"), "sessions_total": 8, "duration_days": 30, "is_active": True}
        )
        for index, child in enumerate(children[:3]):
            sub, _ = Subscription.objects.update_or_create(
                child=child, start_date=month,
                defaults={"tariff": tariff, "end_date": today + timedelta(days=3 + index * 6), "sessions_total": 8, "price": Decimal("5600.00"), "is_active": True},
            )
            Subscription.objects.filter(child=child, is_active=True).exclude(pk=sub.pk).update(is_active=False)
            if index > 0:
                Payment.objects.update_or_create(
                    child=child, subscription=sub, date=month + timedelta(days=index),
                    defaults={"amount": Decimal("5600.00"), "created_by": users["senior"]},
                )
            for day_offset, status in ((-7, Attendance.Status.PRESENT), (-5, Attendance.Status.PRESENT), (-2, Attendance.Status.ABSENT)):
                Attendance.objects.update_or_create(child=child, date=today + timedelta(days=day_offset), slot=None, defaults={"status": status})

        Expense.objects.update_or_create(title="Вода 19 л · 6 бутылей", date=today, defaults={"category": Expense.Category.HOUSEHOLD, "amount": Decimal("2460"), "created_by": users["senior"]})
        Expense.objects.update_or_create(title="Мел и магнезия", date=today-timedelta(days=2), defaults={"category": Expense.Category.EQUIPMENT, "amount": Decimal("4800"), "created_by": users["admin"]})
        RevenueTarget.objects.update_or_create(month=month, defaults={"amount": Decimal("120000"), "set_by": users["boss"]})
        SalaryPayout.objects.update_or_create(trainer=trainer1, month=month, defaults={"amount": Decimal("65000")})
        SalaryPayout.objects.update_or_create(trainer=trainer2, month=month, defaults={"amount": Decimal("58000")})
        ManagerTask.objects.update_or_create(
            title="Подготовить список на соревнования", assignee=users["admin"],
            defaults={"description": "Проверить разряды и годы рождения участников", "created_by": users["boss"], "due_date": today+timedelta(days=1), "is_done": False},
        )
        lead, _ = Lead.objects.update_or_create(
            full_name="Смирнова Виктория", phone="+7 999 555-12-34",
            defaults={"age_text": "7 лет", "source": "VK Реклама · Люберцы", "trial_at": timezone.now() + timedelta(days=1), "trainer": trainer2, "group": junior_group, "imported_from_ad": True},
        )
        Newcomer.objects.update_or_create(
            lead=lead, defaults={"full_name": lead.full_name, "age_text": lead.age_text, "phone": lead.phone, "source": lead.source, "trial_at": lead.trial_at, "trainer": lead.trainer, "group": lead.group, "comment": "Перезвонить утром"},
        )
        Reminder.objects.update_or_create(
            title="Позвонить по заявке", assignee=users["admin"],
            defaults={"description": "Уточнить время пробного занятия", "remind_at": timezone.now() + timedelta(hours=3), "created_by": users["admin"], "visible_to_all": True},
        )

        competition, _ = Competition.objects.update_or_create(name="Кубок «Высота»", defaults={"date": today-timedelta(days=7), "city": "Екатеринбург", "is_internal": True})
        apparatus = []
        for order, name in enumerate(("Прыжок", "Брусья", "Бревно", "Вольные")):
            item, _ = Apparatus.objects.update_or_create(competition=competition, name=name, defaults={"order": order})
            apparatus.append(item)
        scores = ((Decimal("8.900"), Decimal("9.100"), Decimal("8.750"), Decimal("9.200")), (Decimal("8.800"), Decimal("8.950"), Decimal("8.600"), Decimal("9.100")))
        for child, values in zip(children[:2], scores):
            entry, _ = CompetitionEntry.objects.update_or_create(child=child, competition=competition, category="2014–2015", defaults={"rank": "II юн."})
            for item, points in zip(apparatus, values):
                ApparatusScore.objects.update_or_create(entry=entry, apparatus=item, defaults={"points": points})
        entries = list(competition.entries.all())
        entries.sort(key=lambda entry: entry.total_points(), reverse=True)
        for place, entry in enumerate(entries, 1):
            entry.place = place
            entry.save(update_fields=["place"])

        self.stdout.write(self.style.SUCCESS("Демо-данные созданы. Логины: boss, senior, admin. Пароль: Demo12345!"))
