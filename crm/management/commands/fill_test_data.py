import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from crm.models import (
    StaffProfile, Trainer, Group, ScheduleSlot, Child, ChildRank,
    Subscription, Payment, Attendance, Competition, Apparatus,
    CompetitionEntry, ApparatusScore, Camp, CampStay, Expense,
    RevenueTarget, SalaryPayout, ManagerTask,
)

User = get_user_model()

# Списки для генерации разнообразных Игорей
LAST_NAMES = [
    "Иванов", "Петров", "Сидоров", "Кузнецов", "Смирнов",
    "Попов", "Васильев", "Соколов", "Михайлов", "Новиков",
    "Федоров", "Морозов", "Волков", "Алексеев", "Лебедев",
    "Семенов", "Егоров", "Павлов", "Козлов", "Степанов",
]
MIDDLE_NAMES = [
    "Иванович", "Петрович", "Сидорович", "Александрович",
    "Дмитриевич", "Сергеевич", "Андреевич", "Алексеевич",
    "Николаевич", "Михайлович", "Владимирович", "Павлович",
    "Егорович", "Федорович", "Игнатьевич", "Артемович",
    "Борисович", "Викторович", "Григорьевич", "Денисович",
]


class Command(BaseCommand):
    help = "Заполняет базу тестовыми данными (все — Игори, но с разными фамилиями и отчествами)"

    def handle(self, *args, **kwargs):
        self.stdout.write("Создаю Игорей...")

        # --- Пользователи и профили (сотрудники) ---
        roles = ['manager', 'senior_manager', 'chief', 'admin']
        users = []
        for i, role in enumerate(roles, start=1):
            username = f"igor{i}"
            email = f"igor{i}@example.com"
            last_name = random.choice(LAST_NAMES)
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': 'Игорь',
                    'last_name': last_name,
                    'is_staff': True,
                    'role': role,
                }
            )
            if created:
                user.set_password('igor12345')
                user.save()
            StaffProfile.objects.get_or_create(user=user, defaults={'role': role})
            users.append(user)

        # --- Тренеры (тоже Игори с разными фамилиями) ---
        trainers = []
        for i in range(1, 4):
            last_name = random.choice(LAST_NAMES)
            middle_name = random.choice(MIDDLE_NAMES)
            trainer = Trainer.objects.create(
                full_name=f"Игорь {last_name} {middle_name}",
                phone=f"+7-900-000-00-0{i}",
                is_active=True,
                note="Тренер-Игорь",
            )
            trainers.append(trainer)

        # --- Группы ---
        groups = []
        for i, trainer in enumerate(trainers, start=1):
            group = Group.objects.create(
                name=f"Группа {i} (Игорь)",
                trainer=trainer,
                is_active=True,
            )
            groups.append(group)
            # Слоты расписания для группы
            for day in range(0, 3):  # Пн, Вт, Ср
                ScheduleSlot.objects.create(
                    group=group,
                    weekday=day,
                    start_time=f"{10 + day}:00",
                    duration_minutes=60,
                )

        # --- Дети (все — Игори, но разные фамилии и отчества) ---
        children = []
        for i in range(1, 21):  # 20 детей
            last_name = random.choice(LAST_NAMES)
            middle_name = random.choice(MIDDLE_NAMES)
            child = Child.objects.create(
                last_name=last_name,
                first_name="Игорь",
                patronymic=middle_name,
                birth_year=2015 + (i % 5),
                address="г. Игоревск, ул. Игоревская, д. 1",
                parent_name=f"Игорь {last_name} (папа)",
                parent_phone=f"+7-911-111-22-{i:02d}",
                status=random.choice(['active', 'trial', 'archived']),
                trial_from=date.today() - timedelta(days=random.randint(0, 60)),
                discount_percent=random.choice([0, 5, 10, 15]),
                note="Тестовый Игорь",
            )
            # Назначаем группу
            child.group = random.choice(groups)
            # Назначаем личный график (несколько слотов)
            child.save()
            child.schedule.set(random.sample(list(ScheduleSlot.objects.filter(group=child.group)), k=2))
            children.append(child)

            # Разряды по годам
            for year in range(2023, 2026):
                ChildRank.objects.create(
                    child=child,
                    year=year,
                    rank=f"{year - 2022} юн. разряд",
                )

            # Абонемент
            sub = Subscription.objects.create(
                child=child,
                start_date=date.today() - timedelta(days=30),
                end_date=date.today() + timedelta(days=30),
                sessions_total=8,
                price=Decimal("4000.00"),
                promo="Игорь-акция",
            )
            # Оплата
            Payment.objects.create(
                child=child,
                subscription=sub,
                amount=Decimal("4000.00"),
                date=date.today() - timedelta(days=25),
                created_by=random.choice(users),
            )
            # Посещения
            for j in range(0, 8):
                Attendance.objects.create(
                    child=child,
                    date=date.today() - timedelta(days=7 * j),
                    slot=random.choice(child.schedule.all()),
                    status=random.choice(['present', 'absent', 'excused', 'frozen', 'vacation']),
                    comment="Игорь был",
                )

        # --- Соревнования ---
        comp = Competition.objects.create(
            name="Турнир имени Игоря",
            date=date.today() - timedelta(days=30),
            city="Игоревск",
            is_internal=True,
        )
        Apparatus.objects.create(competition=comp, name="Вольные", order=1)
        Apparatus.objects.create(competition=comp, name="Конь", order=2)
        Apparatus.objects.create(competition=comp, name="Кольца", order=3)
        Apparatus.objects.create(competition=comp, name="Опорный прыжок", order=4)

        for child in random.sample(children, 5):
            entry = CompetitionEntry.objects.create(
                child=child,
                competition=comp,
                category="Юноши 2015 г.р.",
                rank="2 юн. разряд",
                place=random.randint(1, 10),
            )
            for app in Apparatus.objects.filter(competition=comp):
                ApparatusScore.objects.create(
                    entry=entry,
                    apparatus=app,
                    points=Decimal(str(round(random.uniform(7.0, 9.5), 2))),
                )

        # --- Лагерь ---
        camp = Camp.objects.create(name="Лагерь 'Игорь'")
        for child in random.sample(children, 3):
            CampStay.objects.create(
                child=child,
                camp=camp,
                start_date=date.today() - timedelta(days=60),
                end_date=date.today() - timedelta(days=50),
            )

        # --- Расходы ---
        Expense.objects.create(
            title="Вода для Игорей",
            amount=Decimal("1500.00"),
            date=date.today() - timedelta(days=10),
            created_by=users[0],
        )

        # --- Цель по выручке ---
        RevenueTarget.objects.create(
            month=date.today().replace(day=1),
            amount=Decimal("100000.00"),
            set_by=users[2],  # начальник
        )

        # --- ЗП тренерам ---
        for trainer in trainers:
            SalaryPayout.objects.create(
                trainer=trainer,
                month=date.today().replace(day=1),
                amount=Decimal("30000.00"),
            )

        # --- Задачи менеджерам ---
        ManagerTask.objects.create(
            title="Позвонить всем Игорям",
            description="Обзвонить клиентов по имени Игорь и предложить скидку.",
            assignee=users[0],
            created_by=users[2],
            due_date=date.today() + timedelta(days=3),
            is_done=False,
        )

        self.stdout.write(self.style.SUCCESS("✅ База заполнена! Все — Игори, но с разнообразием."))