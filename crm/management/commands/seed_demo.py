from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import (
    Apparatus,
    ApparatusScore,
    Attendance,
    AuditEvent,
    Branch,
    Camp,
    CampStay,
    Child,
    ChildRank,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    ManagerTask,
    Newcomer,
    Payment,
    Reminder,
    RevenueTarget,
    Role,
    SalaryAdjustment,
    SalaryPayout,
    ScheduleSlot,
    StaffProfile,
    Subscription,
    Tariff,
    Trainer,
)


class Command(BaseCommand):
    help = "Создаёт насыщенные идемпотентные демо-данные CRM"

    DEMO_PASSWORD = "Demo12345!"

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()
        now = timezone.now()
        month = today.replace(day=1)
        previous_month = (month - timedelta(days=1)).replace(day=1)
        user_model = get_user_model()

        # ------------------------------------------------------------------
        # Пользователи и роли
        # В проекте сейчас две системы ролей:
        #   User.role: manager / senior_manager / chief / admin
        #   StaffProfile.role: manager / senior / boss
        # Поэтому seed заполняет обе согласованно.
        # ------------------------------------------------------------------
        account_data = [
            {
                "username": "boss",
                "first_name": "Сергей",
                "last_name": "Андреев",
                "user_role": "chief",
                "profile_role": Role.BOSS,
                "is_superuser": True,
            },
            {
                "username": "senior",
                "first_name": "Мария",
                "last_name": "Кокорина",
                "user_role": "senior_manager",
                "profile_role": Role.SENIOR,
                "is_superuser": False,
            },
            {
                "username": "admin2",
                "first_name": "Елена",
                "last_name": "Романова",
                "user_role": "manager",
                "profile_role": Role.MANAGER,
                "is_superuser": False,
            },
        ]

        users = {}
        for item in account_data:
            user, _ = user_model.objects.update_or_create(
                username=item["username"],
                defaults={
                    "first_name": item["first_name"],
                    "last_name": item["last_name"],
                    "role": item["user_role"],
                    "is_staff": True,
                    "is_active": True,
                    "is_superuser": item["is_superuser"],
                },
            )
            user.set_password(self.DEMO_PASSWORD)
            user.save()
            users[item["username"]] = user

            StaffProfile.objects.update_or_create(
                user=user,
                defaults={"role": item["profile_role"]},
            )

        # ------------------------------------------------------------------
        # Филиалы
        # ------------------------------------------------------------------
        lyubertsy, _ = Branch.objects.update_or_create(
            name="Люберцы",
            defaults={
                "address": "Московская область, г. Люберцы, Октябрьский проспект, 145",
                "is_active": True,
            },
        )
        kotelniki, _ = Branch.objects.update_or_create(
            name="Котельники",
            defaults={
                "address": "Московская область, г. Котельники, мкр. Белая Дача, 12",
                "is_active": True,
            },
        )
        archive_branch, _ = Branch.objects.update_or_create(
            name="Старый зал",
            defaults={
                "address": "Демо-филиал для проверки архива",
                "is_active": False,
            },
        )

        user_branch = {
            "boss": None,
            "senior": lyubertsy,
            "admin": lyubertsy,
            "admin2": kotelniki,
        }
        shift_anchors = {
            "senior": today - timedelta(days=2),
            "admin": today,
            "admin2": today - timedelta(days=1),
        }

        for username, branch in user_branch.items():
            user = users[username]
            user.branch = branch
            user.save(update_fields=["branch"])

            profile = user.profile
            profile.branch = branch
            profile.shift_anchor = shift_anchors.get(username)
            profile.save(update_fields=["branch", "shift_anchor"])

        # ------------------------------------------------------------------
        # Тренеры
        # ------------------------------------------------------------------
        trainer1, _ = Trainer.objects.update_or_create(
            full_name="Ольга Воронова",
            defaults={
                "phone": "+7 900 111-22-33",
                "is_active": True,
                "note": "Старшие группы, подготовка к соревнованиям",
            },
        )
        trainer2, _ = Trainer.objects.update_or_create(
            full_name="Анна Миронова",
            defaults={
                "phone": "+7 900 222-33-44",
                "is_active": True,
                "note": "Младшие группы и пробные занятия",
            },
        )
        trainer3, _ = Trainer.objects.update_or_create(
            full_name="Ирина Белова",
            defaults={
                "phone": "+7 900 333-44-55",
                "is_active": True,
                "note": "Средняя группа, филиал Котельники",
            },
        )
        Trainer.objects.update_or_create(
            full_name="Екатерина Лукина",
            defaults={
                "phone": "+7 900 444-55-66",
                "is_active": False,
                "note": "Уволена. Оставлена в demo для проверки архивных связей.",
            },
        )

        # ------------------------------------------------------------------
        # Группы
        # ------------------------------------------------------------------
        senior_group, _ = Group.objects.update_or_create(
            name="Старшая группа",
            defaults={
                "trainer": trainer1,
                "branch": lyubertsy,
                "single_session_price": Decimal("900.00"),
                "salary_rate": Decimal("350.00"),
                "is_active": True,
            },
        )
        junior_group, _ = Group.objects.update_or_create(
            name="Младшая группа",
            defaults={
                "trainer": trainer2,
                "branch": lyubertsy,
                "single_session_price": Decimal("800.00"),
                "salary_rate": Decimal("300.00"),
                "is_active": True,
            },
        )
        middle_group, _ = Group.objects.update_or_create(
            name="Средняя группа · Котельники",
            defaults={
                "trainer": trainer3,
                "branch": kotelniki,
                "single_session_price": Decimal("850.00"),
                "salary_rate": Decimal("320.00"),
                "is_active": True,
            },
        )
        archived_group, _ = Group.objects.update_or_create(
            name="Архивная группа",
            defaults={
                "trainer": trainer1,
                "branch": archive_branch,
                "single_session_price": Decimal("700.00"),
                "salary_rate": Decimal("250.00"),
                "is_active": False,
            },
        )

        schedule_definitions = {
            senior_group: ((0, time(18, 0)), (2, time(18, 0)), (5, time(11, 0))),
            junior_group: ((1, time(16, 0)), (3, time(16, 0)), (5, time(9, 30))),
            middle_group: ((0, time(17, 0)), (3, time(17, 0)), (6, time(11, 30))),
            archived_group: ((4, time(19, 0)),),
        }

        slots_by_group = {}
        for group, definitions in schedule_definitions.items():
            slots_by_group[group.pk] = []
            for weekday, start_time in definitions:
                slot, _ = ScheduleSlot.objects.update_or_create(
                    group=group,
                    weekday=weekday,
                    start_time=start_time,
                    defaults={"duration_minutes": 90},
                )
                slots_by_group[group.pk].append(slot)

        # ------------------------------------------------------------------
        # Дети
        # ------------------------------------------------------------------
        children_data = [
            {
                "last_name": "Соколова",
                "first_name": "Алиса",
                "patronymic": "Ильинична",
                "birth_date": today.replace(year=today.year - 11, month=4, day=12),
                "group": senior_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Елена Соколова",
                "parent_phone": "+7 912 345-67-89",
                "address": "Люберцы, ул. Кирова, 18",
                "discount": 0,
                "note": "Основной активный клиент. Абонемент оплачен полностью.",
            },
            {
                "last_name": "Кузнецова",
                "first_name": "Мария",
                "patronymic": "Алексеевна",
                "birth_date": today.replace(year=today.year - 12, month=8, day=21),
                "group": senior_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Наталья Кузнецова",
                "parent_phone": "+7 922 100-24-11",
                "address": "Люберцы, ул. Побратимов, 9",
                "discount": 5,
                "note": "Есть частичная задолженность по текущему абонементу.",
            },
            {
                "last_name": "Петрова",
                "first_name": "Анна",
                "patronymic": "Дмитриевна",
                "birth_date": today.replace(year=today.year - 10, month=2, day=3),
                "group": junior_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Ирина Петрова",
                "parent_phone": "+7 999 120-44-31",
                "address": "Люберцы, Комсомольский проспект, 14",
                "discount": 0,
                "note": "Есть небольшая переплата на балансе.",
            },
            {
                "last_name": "Егорова",
                "first_name": "Варвара",
                "patronymic": "Сергеевна",
                "birth_date": today.replace(year=today.year - 9, month=11, day=7),
                "group": junior_group,
                "status": Child.Status.TRIAL,
                "parent_name": "Ольга Егорова",
                "parent_phone": "+7 912 800-10-20",
                "address": "Люберцы, ул. 3-е Почтовое отделение, 61",
                "discount": 0,
                "trial_from": today - timedelta(days=5),
                "note": "Пробный период ещё действует.",
            },
            {
                "last_name": "Морозов",
                "first_name": "Артём",
                "patronymic": "Максимович",
                "birth_date": today.replace(year=today.year - 11, month=6, day=15),
                "group": senior_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Максим Морозов",
                "parent_phone": "+7 926 321-18-90",
                "address": "Люберцы, ул. Воинов-Интернационалистов, 7",
                "discount": 10,
                "note": "Абонемент заканчивается в ближайшие 7 дней.",
            },
            {
                "last_name": "Лебедева",
                "first_name": "Ева",
                "patronymic": "Романовна",
                "birth_date": today.replace(year=today.year - 9, month=1, day=19),
                "group": junior_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Роман Лебедев",
                "parent_phone": "+7 985 111-70-30",
                "address": "Люберцы, ул. Наташинская, 16",
                "discount": 0,
                "note": "Активна, но новый абонемент ещё не оформлен; есть занятия в долг.",
            },
            {
                "last_name": "Фёдорова",
                "first_name": "София",
                "patronymic": "Игоревна",
                "birth_date": today.replace(year=today.year - 8, month=9, day=2),
                "group": junior_group,
                "status": Child.Status.TRIAL,
                "parent_name": "Игорь Фёдоров",
                "parent_phone": "+7 903 880-20-10",
                "address": "Люберцы, ул. Юбилейная, 23",
                "discount": 0,
                "trial_from": today - timedelta(days=16),
                "note": "Пробный период истёк — тест системного предупреждения.",
            },
            {
                "last_name": "Волков",
                "first_name": "Михаил",
                "patronymic": "Олегович",
                "birth_date": today.replace(year=today.year - 12, month=12, day=1),
                "group": archived_group,
                "status": Child.Status.ARCHIVED,
                "parent_name": "Олег Волков",
                "parent_phone": "+7 916 200-45-18",
                "address": "Котельники, мкр. Силикат, 8",
                "discount": 0,
                "archived_at": today - timedelta(days=40),
                "note": "Архивная карточка.",
            },
            {
                "last_name": "Орлова",
                "first_name": "Полина",
                "patronymic": "Андреевна",
                "birth_date": today.replace(year=today.year - 10, month=3, day=28),
                "group": senior_group,
                "status": Child.Status.LOST,
                "parent_name": "Андрей Орлов",
                "parent_phone": "+7 925 460-88-00",
                "address": "Люберцы, ул. Инициативная, 5",
                "discount": 0,
                "archived_at": today - timedelta(days=24),
                "note": "Потерянный клиент — перестали отвечать.",
            },
            {
                "last_name": "Белова",
                "first_name": "Ксения",
                "patronymic": "Павловна",
                "birth_date": today.replace(year=today.year - 10, month=7, day=8),
                "group": middle_group,
                "status": Child.Status.ACTIVE,
                "parent_name": "Павел Белов",
                "parent_phone": "+7 977 502-70-70",
                "address": "Котельники, 2-й Покровский проезд, 6",
                "discount": 10,
                "note": "Индивидуальный график: посещает только два слота группы.",
            },
        ]

        children = {}
        for data in children_data:
            birth_date = data["birth_date"]
            child, _ = Child.objects.update_or_create(
                last_name=data["last_name"],
                first_name=data["first_name"],
                defaults={
                    "patronymic": data["patronymic"],
                    "birth_year": birth_date.year,
                    "birth_date": birth_date,
                    "address": data["address"],
                    "parent_name": data["parent_name"],
                    "parent_phone": data["parent_phone"],
                    "group": data["group"],
                    "status": data["status"],
                    "trial_from": data.get("trial_from"),
                    "discount_percent": data["discount"],
                    "note": data["note"],
                    "archived_at": data.get("archived_at"),
                },
            )
            children[f"{data['last_name']} {data['first_name']}"] = child

        alice = children["Соколова Алиса"]
        maria = children["Кузнецова Мария"]
        anna = children["Петрова Анна"]
        varvara = children["Егорова Варвара"]
        artem = children["Морозов Артём"]
        eva = children["Лебедева Ева"]
        sofia = children["Фёдорова София"]
        mikhail = children["Волков Михаил"]
        polina = children["Орлова Полина"]
        ksenia = children["Белова Ксения"]

        # Индивидуальный график Ксении — только Пн и Чт из графика её группы.
        ksenia.schedule.set(
            [slot for slot in slots_by_group[middle_group.pk] if slot.weekday in (0, 3)]
        )

        # ------------------------------------------------------------------
        # Разряды
        # ------------------------------------------------------------------
        rank_rows = [
            (alice, today.year - 1, "III юн."),
            (alice, today.year, "II юн."),
            (maria, today.year - 1, "II юн."),
            (maria, today.year, "I юн."),
            (anna, today.year, "III юн."),
            (artem, today.year, "II юн."),
            (ksenia, today.year, "III юн."),
        ]
        for child, year, rank in rank_rows:
            ChildRank.objects.update_or_create(
                child=child,
                year=year,
                defaults={"rank": rank},
            )

        # ------------------------------------------------------------------
        # Тарифы
        # ------------------------------------------------------------------
        tariff4, _ = Tariff.objects.update_or_create(
            name="4 занятия",
            defaults={
                "price": Decimal("3600.00"),
                "sessions_total": 4,
                "duration_days": 30,
                "is_active": True,
            },
        )
        tariff8, _ = Tariff.objects.update_or_create(
            name="8 занятий",
            defaults={
                "price": Decimal("5600.00"),
                "sessions_total": 8,
                "duration_days": 30,
                "is_active": True,
            },
        )
        tariff12, _ = Tariff.objects.update_or_create(
            name="12 занятий",
            defaults={
                "price": Decimal("7800.00"),
                "sessions_total": 12,
                "duration_days": 45,
                "is_active": True,
            },
        )
        Tariff.objects.update_or_create(
            name="Старый тариф 8 занятий",
            defaults={
                "price": Decimal("4900.00"),
                "sessions_total": 8,
                "duration_days": 30,
                "is_active": False,
            },
        )

        def seed_subscription(
            child,
            tariff,
            start_date,
            end_date,
            price=None,
            sessions_total=None,
            promo="",
            is_active=True,
        ):
            subscription, _ = Subscription.objects.update_or_create(
                child=child,
                start_date=start_date,
                end_date=end_date,
                defaults={
                    "tariff": tariff,
                    "sessions_total": sessions_total or tariff.sessions_total,
                    "price": price if price is not None else tariff.price,
                    "promo": promo,
                    "is_active": is_active,
                },
            )
            if is_active:
                Subscription.objects.filter(child=child, is_active=True).exclude(
                    pk=subscription.pk
                ).update(is_active=False)
            return subscription

        # Для активных demo-абонементов start_date = первое число текущего
        # месяца. Это совместимо со старым seed и позволяет обновить старые
        # записи, а не создавать вторую копию абонемента.
        alice_sub = seed_subscription(
            alice,
            tariff8,
            month,
            today + timedelta(days=10),
        )
        maria_sub = seed_subscription(
            maria,
            tariff8,
            month,
            today + timedelta(days=15),
        )
        anna_sub = seed_subscription(
            anna,
            tariff8,
            month,
            today + timedelta(days=20),
            promo="Первый месяц",
        )
        artem_sub = seed_subscription(
            artem,
            tariff4,
            month,
            today + timedelta(days=5),
            price=Decimal("3240.00"),
            promo="Скидка 10%",
        )
        ksenia_sub = seed_subscription(
            ksenia,
            tariff12,
            month,
            today + timedelta(days=20),
            price=Decimal("7020.00"),
            promo="Семейная скидка 10%",
        )

        # Исторический абонемент Евы закончился, нового пока нет.
        eva_sub = seed_subscription(
            eva,
            tariff4,
            previous_month,
            month - timedelta(days=1),
            is_active=False,
        )

        # Исторические абонементы для архива/потерянного клиента.
        seed_subscription(
            mikhail,
            tariff8,
            today - timedelta(days=100),
            today - timedelta(days=70),
            is_active=False,
        )
        seed_subscription(
            polina,
            tariff8,
            today - timedelta(days=75),
            today - timedelta(days=45),
            is_active=False,
        )

        # ------------------------------------------------------------------
        # Оплаты
        # ------------------------------------------------------------------
        def seed_payment(child, subscription, amount, payment_date, created_by):
            return Payment.objects.update_or_create(
                child=child,
                subscription=subscription,
                date=payment_date,
                defaults={
                    "amount": Decimal(amount),
                    "created_by": created_by,
                },
            )[0]

        seed_payment(alice, alice_sub, "5600.00", month, users["senior"])
        # Даты Марии и Анны совпадают со старым demo seed, поэтому старые
        # платежи будут обновлены, а не продублированы.
        seed_payment(maria, maria_sub, "3000.00", month + timedelta(days=1), users["admin"])
        seed_payment(anna, anna_sub, "6000.00", month + timedelta(days=2), users["senior"])
        seed_payment(artem, artem_sub, "3240.00", month + timedelta(days=3), users["senior"])
        seed_payment(ksenia, ksenia_sub, "7020.00", month + timedelta(days=4), users["admin2"])
        seed_payment(eva, eva_sub, "3600.00", previous_month + timedelta(days=3), users["admin"])

        # ------------------------------------------------------------------
        # Посещения
        # Используем реальные ScheduleSlot, а не slot=None.
        # ------------------------------------------------------------------
        def past_scheduled_pairs(group, count):
            """Последние count пар (дата, слот) по графику группы."""
            group_slots = list(slots_by_group[group.pk])
            result = []
            cursor = today - timedelta(days=1)
            while len(result) < count:
                for slot in group_slots:
                    if slot.weekday == cursor.weekday():
                        result.append((cursor, slot))
                        if len(result) >= count:
                            break
                cursor -= timedelta(days=1)
            result.sort(key=lambda pair: pair[0])
            return result

        def seed_attendance(child, date, slot, status, comment="", charge="0.00"):
            Attendance.objects.update_or_create(
                child=child,
                date=date,
                slot=slot,
                defaults={
                    "status": status,
                    "comment": comment,
                    "charge_amount": Decimal(charge),
                },
            )

        # У старого demo seed отметки создавались с slot=None. Удаляем
        # только такие legacy-строки у наших demo-детей, чтобы они не
        # искажали sessions_left(), missed_percent() и debt_sessions().
        Attendance.objects.filter(
            child__in=list(children.values()),
            slot__isnull=True,
        ).delete()

        # Алиса: все типы отметок для проверки табеля.
        alice_pairs = past_scheduled_pairs(senior_group, 6)
        alice_statuses = [
            (Attendance.Status.PRESENT, "Обычное посещение", "0.00"),
            (Attendance.Status.PRESENT, "", "0.00"),
            (Attendance.Status.ABSENT, "Не предупредили", "0.00"),
            (Attendance.Status.EXCUSED, "Справка от врача", "0.00"),
            (Attendance.Status.FROZEN, "Заморозка по заявлению", "0.00"),
            (Attendance.Status.VACATION, "Семейная поездка", "0.00"),
        ]
        for (date_value, slot), (status, comment, charge) in zip(
            alice_pairs, alice_statuses
        ):
            seed_attendance(alice, date_value, slot, status, comment, charge)

        # Мария: несколько использованных занятий при частичной оплате.
        for index, (date_value, slot) in enumerate(past_scheduled_pairs(senior_group, 5)):
            status = Attendance.Status.ABSENT if index == 2 else Attendance.Status.PRESENT
            seed_attendance(
                maria,
                date_value,
                slot,
                status,
                "Пропуск без переноса" if status == Attendance.Status.ABSENT else "",
            )

        # Анна: стабильное посещение.
        for date_value, slot in past_scheduled_pairs(junior_group, 4):
            seed_attendance(anna, date_value, slot, Attendance.Status.PRESENT)

        # Артём: почти израсходовал короткий абонемент.
        artem_pairs = past_scheduled_pairs(senior_group, 3)
        for date_value, slot in artem_pairs:
            seed_attendance(artem, date_value, slot, Attendance.Status.PRESENT)

        # Ева: 4 оплаченных + 2 занятия в долг по 800 ₽.
        eva_pairs = past_scheduled_pairs(junior_group, 6)
        for index, (date_value, slot) in enumerate(eva_pairs):
            charge = "800.00" if index >= 4 else "0.00"
            seed_attendance(
                eva,
                date_value,
                slot,
                Attendance.Status.PRESENT,
                "Занятие в долг" if index >= 4 else "",
                charge,
            )

        # Ксения: персональный график, включая один уважительный пропуск.
        ksenia_pairs = [
            pair
            for pair in past_scheduled_pairs(middle_group, 8)
            if pair[1].weekday in (0, 3)
        ][-5:]
        for index, (date_value, slot) in enumerate(ksenia_pairs):
            seed_attendance(
                ksenia,
                date_value,
                slot,
                Attendance.Status.EXCUSED if index == 1 else Attendance.Status.PRESENT,
                "Школьное мероприятие" if index == 1 else "",
            )

        # ------------------------------------------------------------------
        # Корректировки и выплаты зарплаты
        # ------------------------------------------------------------------
        salary_adjustments = [
            (trainer1, month, "Персональная тренировка", "2500.00"),
            (trainer1, month, "Подготовка к соревнованиям", "6000.00"),
            (trainer2, month, "Замена тренера", "1800.00"),
            (trainer3, month, "Выездное мероприятие", "3500.00"),
            (trainer1, previous_month, "Соревнования", "5000.00"),
        ]
        for trainer, salary_month, title, amount in salary_adjustments:
            SalaryAdjustment.objects.update_or_create(
                trainer=trainer,
                month=salary_month,
                title=title,
                defaults={"amount": Decimal(amount)},
            )

        salary_payouts = [
            (trainer1, month, "65000.00"),
            (trainer2, month, "58000.00"),
            (trainer3, month, "54000.00"),
            (trainer1, previous_month, "63500.00"),
            (trainer2, previous_month, "57000.00"),
            (trainer3, previous_month, "52000.00"),
        ]
        for trainer, payout_month, amount in salary_payouts:
            SalaryPayout.objects.update_or_create(
                trainer=trainer,
                month=payout_month,
                defaults={"amount": Decimal(amount)},
            )

        # ------------------------------------------------------------------
        # Расходы и цели по выручке
        # ------------------------------------------------------------------
        expense_rows = [
            (
                "Вода 19 л · 6 бутылей",
                Expense.Category.HOUSEHOLD,
                "2460.00",
                today,
                users["senior"],
            ),
            (
                "Мел и магнезия",
                Expense.Category.EQUIPMENT,
                "4800.00",
                today - timedelta(days=2),
                users["admin"],
            ),
            (
                "Замена ламп в раздевалке",
                Expense.Category.REPAIR,
                "3200.00",
                today - timedelta(days=5),
                users["senior"],
            ),
            (
                "Бумага и канцелярия",
                Expense.Category.HOUSEHOLD,
                "1750.00",
                today - timedelta(days=8),
                users["admin2"],
            ),
            (
                "Ремонт гимнастического мата",
                Expense.Category.REPAIR,
                "8900.00",
                previous_month + timedelta(days=12),
                users["senior"],
            ),
            (
                "Такси тренеру после соревнований",
                Expense.Category.OTHER,
                "2100.00",
                previous_month + timedelta(days=18),
                users["boss"],
            ),
        ]
        for title, category, amount, expense_date, created_by in expense_rows:
            Expense.objects.update_or_create(
                title=title,
                defaults={
                    "category": category,
                    "amount": Decimal(amount),
                    "date": expense_date,
                    "created_by": created_by,
                },
            )

        RevenueTarget.objects.update_or_create(
            month=month,
            defaults={
                "amount": Decimal("420000.00"),
                "set_by": users["boss"],
            },
        )
        RevenueTarget.objects.update_or_create(
            month=previous_month,
            defaults={
                "amount": Decimal("390000.00"),
                "set_by": users["boss"],
            },
        )

        # ------------------------------------------------------------------
        # Задачи менеджеров
        # ------------------------------------------------------------------
        task_rows = [
            {
                "title": "Подготовить список на соревнования",
                "assignee": users["admin"],
                "description": "Проверить разряды и годы рождения участников.",
                "created_by": users["boss"],
                "due_date": today + timedelta(days=1),
                "is_done": False,
            },
            {
                "title": "Проверить задолженности по абонементам",
                "assignee": users["senior"],
                "description": "Связаться с родителями детей с задолженностью более 1 000 ₽.",
                "created_by": users["boss"],
                "due_date": today,
                "is_done": False,
            },
            {
                "title": "Заказать магнезию",
                "assignee": users["admin2"],
                "description": "Остался запас примерно на неделю.",
                "created_by": users["senior"],
                "due_date": today - timedelta(days=2),
                "is_done": False,
            },
            {
                "title": "Обновить контакты родителей",
                "assignee": None,
                "description": "Общая задача для администраторов.",
                "created_by": users["boss"],
                "due_date": today + timedelta(days=7),
                "is_done": False,
            },
            {
                "title": "Сверить оплаты за прошлый месяц",
                "assignee": users["senior"],
                "description": "Сверка завершена.",
                "created_by": users["boss"],
                "due_date": today - timedelta(days=4),
                "is_done": True,
                "done_at": now - timedelta(days=3),
            },
        ]
        for row in task_rows:
            ManagerTask.objects.update_or_create(
                title=row["title"],
                assignee=row["assignee"],
                defaults={
                    "description": row["description"],
                    "created_by": row["created_by"],
                    "due_date": row["due_date"],
                    "is_done": row["is_done"],
                    "done_at": row.get("done_at"),
                },
            )

        # ------------------------------------------------------------------
        # Напоминания
        # ------------------------------------------------------------------
        reminder_rows = [
            {
                "title": "Позвонить по новой заявке",
                "assignee": users["admin"],
                "description": "Уточнить время пробного занятия.",
                "remind_at": now + timedelta(hours=3),
                "created_by": users["admin"],
                "is_done": False,
                "visible_to_all": True,
            },
            {
                "title": "Напомнить об оплате Марии Кузнецовой",
                "assignee": users["senior"],
                "description": "По текущему абонементу внесена только часть суммы.",
                "remind_at": now + timedelta(days=1, hours=1),
                "created_by": users["senior"],
                "is_done": False,
                "visible_to_all": False,
            },
            {
                "title": "Проверить просроченную задачу",
                "assignee": users["admin2"],
                "description": "Демо просроченного напоминания.",
                "remind_at": now - timedelta(hours=5),
                "created_by": users["senior"],
                "is_done": False,
                "visible_to_all": True,
            },
            {
                "title": "Отправить расписание тренеру",
                "assignee": users["admin"],
                "description": "Выполненное напоминание.",
                "remind_at": now - timedelta(days=2),
                "created_by": users["admin"],
                "is_done": True,
                "visible_to_all": False,
            },
        ]
        for row in reminder_rows:
            Reminder.objects.update_or_create(
                title=row["title"],
                assignee=row["assignee"],
                defaults={
                    "description": row["description"],
                    "remind_at": row["remind_at"],
                    "created_by": row["created_by"],
                    "is_done": row["is_done"],
                    "visible_to_all": row["visible_to_all"],
                },
            )

        # ------------------------------------------------------------------
        # Лиды и новички
        # ------------------------------------------------------------------
        lead_rows = [
            {
                "key": "victoria",
                "full_name": "Смирнова Виктория",
                "phone": "+7 999 555-12-34",
                "birth_date": today.replace(year=today.year - 7, month=5, day=17),
                "age_text": "7 лет",
                "source": "VK Реклама · Люберцы",
                "trial_at": now + timedelta(days=1),
                "trainer": trainer2,
                "group": junior_group,
                "status": Lead.Status.NEW,
                "comment": "Мама просила позвонить после 18:00.",
                "imported_from_ad": True,
                "child": None,
            },
            {
                "key": "daria",
                "full_name": "Николаева Дарья",
                "phone": "+7 926 210-90-11",
                "birth_date": today.replace(year=today.year - 8, month=10, day=11),
                "age_text": "8 лет",
                "source": "Яндекс Карты",
                "trial_at": now + timedelta(days=2, hours=2),
                "trainer": trainer2,
                "group": junior_group,
                "status": Lead.Status.CONTACTED,
                "comment": "Время согласовано предварительно.",
                "imported_from_ad": False,
                "child": None,
            },
            {
                "key": "alena",
                "full_name": "Громова Алёна",
                "phone": "+7 903 678-14-70",
                "birth_date": today.replace(year=today.year - 10, month=6, day=4),
                "age_text": "10 лет",
                "source": "Рекомендация",
                "trial_at": now - timedelta(days=1),
                "trainer": trainer3,
                "group": middle_group,
                "status": Lead.Status.QUALIFIED,
                "comment": "Пробное прошло хорошо, думают над абонементом.",
                "imported_from_ad": False,
                "child": None,
            },
            {
                "key": "roman",
                "full_name": "Крылов Роман",
                "phone": "+7 915 410-33-29",
                "birth_date": today.replace(year=today.year - 9, month=2, day=14),
                "age_text": "9 лет",
                "source": "VK Реклама · Котельники",
                "trial_at": None,
                "trainer": trainer3,
                "group": middle_group,
                "status": Lead.Status.LOST,
                "comment": "Не подходит расписание.",
                "imported_from_ad": True,
                "child": None,
            },
            {
                "key": "converted",
                "full_name": "Егорова Варвара",
                "phone": varvara.parent_phone,
                "birth_date": varvara.birth_date,
                "age_text": varvara.age_display(),
                "source": "Сайт",
                "trial_at": now - timedelta(days=5),
                "trainer": trainer2,
                "group": junior_group,
                "status": Lead.Status.QUALIFIED,
                "comment": "Создана карточка спортсмена, идёт пробный период.",
                "imported_from_ad": True,
                "child": varvara,
            },
        ]

        leads = {}
        for row in lead_rows:
            lead, _ = Lead.objects.update_or_create(
                full_name=row["full_name"],
                phone=row["phone"],
                defaults={
                    "birth_date": row["birth_date"],
                    "age_text": row["age_text"],
                    "source": row["source"],
                    "trial_at": row["trial_at"],
                    "trainer": row["trainer"],
                    "group": row["group"],
                    "status": row["status"],
                    "comment": row["comment"],
                    "imported_from_ad": row["imported_from_ad"],
                    "child": row["child"],
                },
            )
            leads[row["key"]] = lead

        newcomer_rows = [
            {
                "lead": leads["victoria"],
                "full_name": leads["victoria"].full_name,
                "birth_date": leads["victoria"].birth_date,
                "age_text": leads["victoria"].age_text,
                "phone": leads["victoria"].phone,
                "source": leads["victoria"].source,
                "trial_at": leads["victoria"].trial_at,
                "trainer": trainer2,
                "group": junior_group,
                "attended": False,
                "paid": False,
                "lesson_cancelled": False,
                "comment": "Перезвонить утром.",
                "child": None,
            },
            {
                "lead": leads["daria"],
                "full_name": leads["daria"].full_name,
                "birth_date": leads["daria"].birth_date,
                "age_text": leads["daria"].age_text,
                "phone": leads["daria"].phone,
                "source": leads["daria"].source,
                "trial_at": leads["daria"].trial_at,
                "trainer": trainer2,
                "group": junior_group,
                "attended": False,
                "paid": False,
                "lesson_cancelled": False,
                "comment": "Записана на пробное.",
                "child": None,
            },
            {
                "lead": leads["alena"],
                "full_name": leads["alena"].full_name,
                "birth_date": leads["alena"].birth_date,
                "age_text": leads["alena"].age_text,
                "phone": leads["alena"].phone,
                "source": leads["alena"].source,
                "trial_at": leads["alena"].trial_at,
                "trainer": trainer3,
                "group": middle_group,
                "attended": True,
                "paid": False,
                "lesson_cancelled": False,
                "comment": "Была на пробном, решение по оплате завтра.",
                "child": None,
            },
            {
                "lead": leads["converted"],
                "full_name": leads["converted"].full_name,
                "birth_date": leads["converted"].birth_date,
                "age_text": leads["converted"].age_text,
                "phone": leads["converted"].phone,
                "source": leads["converted"].source,
                "trial_at": leads["converted"].trial_at,
                "trainer": trainer2,
                "group": junior_group,
                "attended": True,
                "paid": True,
                "lesson_cancelled": False,
                "comment": "Конвертирована в спортсмена.",
                "child": varvara,
            },
            {
                "lead": leads["roman"],
                "full_name": leads["roman"].full_name,
                "birth_date": leads["roman"].birth_date,
                "age_text": leads["roman"].age_text,
                "phone": leads["roman"].phone,
                "source": leads["roman"].source,
                "trial_at": now - timedelta(days=3),
                "trainer": trainer3,
                "group": middle_group,
                "attended": False,
                "paid": False,
                "lesson_cancelled": True,
                "comment": "Пробное отменено родителем.",
                "child": None,
            },
        ]

        for row in newcomer_rows:
            Newcomer.objects.update_or_create(
                lead=row["lead"],
                full_name=row["full_name"],
                defaults={
                    "birth_date": row["birth_date"],
                    "age_text": row["age_text"],
                    "phone": row["phone"],
                    "source": row["source"],
                    "trial_at": row["trial_at"],
                    "trainer": row["trainer"],
                    "group": row["group"],
                    "attended": row["attended"],
                    "paid": row["paid"],
                    "lesson_cancelled": row["lesson_cancelled"],
                    "comment": row["comment"],
                    "child": row["child"],
                },
            )

        # ------------------------------------------------------------------
        # Соревнования, снаряды, результаты
        # ------------------------------------------------------------------
        def seed_competition(name, date, city, is_internal, apparatus_names, entries):
            competition, _ = Competition.objects.update_or_create(
                name=name,
                defaults={
                    "date": date,
                    "city": city,
                    "is_internal": is_internal,
                },
            )

            apparatus_list = []
            for order, apparatus_name in enumerate(apparatus_names):
                apparatus, _ = Apparatus.objects.update_or_create(
                    competition=competition,
                    name=apparatus_name,
                    defaults={"order": order},
                )
                apparatus_list.append(apparatus)

            touched_entries = []
            for row in entries:
                entry, _ = CompetitionEntry.objects.update_or_create(
                    child=row["child"],
                    competition=competition,
                    category=row["category"],
                    defaults={"rank": row["rank"]},
                )
                for apparatus, points in zip(apparatus_list, row["scores"]):
                    ApparatusScore.objects.update_or_create(
                        entry=entry,
                        apparatus=apparatus,
                        defaults={"points": Decimal(points)},
                    )
                touched_entries.append(entry)

            # Места считаем отдельно внутри каждой категории.
            categories = sorted({entry.category for entry in touched_entries})
            for category in categories:
                category_entries = [
                    entry for entry in touched_entries if entry.category == category
                ]
                category_entries.sort(
                    key=lambda entry: entry.total_points(), reverse=True
                )
                for place, entry in enumerate(category_entries, 1):
                    entry.place = place
                    entry.save(update_fields=["place"])

            return competition

        seed_competition(
            name="Кубок «Высота»",
            date=today - timedelta(days=7),
            city="Екатеринбург",
            is_internal=True,
            apparatus_names=("Прыжок", "Брусья", "Бревно", "Вольные"),
            entries=[
                {
                    "child": alice,
                    "category": "2014–2015",
                    "rank": "II юн.",
                    "scores": ("8.900", "9.100", "8.750", "9.200"),
                },
                {
                    "child": maria,
                    "category": "2014–2015",
                    "rank": "I юн.",
                    "scores": ("8.800", "8.950", "8.600", "9.100"),
                },
                {
                    "child": artem,
                    "category": "2014–2015",
                    "rank": "II юн.",
                    "scores": ("8.500", "8.720", "8.810", "8.900"),
                },
                {
                    "child": anna,
                    "category": "2016–2017",
                    "rank": "III юн.",
                    "scores": ("8.400", "8.650", "8.520", "8.740"),
                },
            ],
        )

        seed_competition(
            name="Открытое первенство Московской области",
            date=today - timedelta(days=38),
            city="Балашиха",
            is_internal=False,
            apparatus_names=("Прыжок", "Брусья", "Бревно", "Вольные"),
            entries=[
                {
                    "child": alice,
                    "category": "2015",
                    "rank": "III юн.",
                    "scores": ("8.500", "8.700", "8.550", "8.900"),
                },
                {
                    "child": ksenia,
                    "category": "2016",
                    "rank": "III юн.",
                    "scores": ("8.350", "8.600", "8.420", "8.710"),
                },
            ],
        )

        # ------------------------------------------------------------------
        # Лагеря
        # ------------------------------------------------------------------
        summer_camp, _ = Camp.objects.update_or_create(name="Летние сборы · Сочи")
        winter_camp, _ = Camp.objects.update_or_create(name="Зимние сборы · Казань")

        camp_stays = [
            (
                alice,
                summer_camp,
                today - timedelta(days=80),
                today - timedelta(days=66),
            ),
            (
                maria,
                summer_camp,
                today - timedelta(days=80),
                today - timedelta(days=66),
            ),
            (
                artem,
                winter_camp,
                today - timedelta(days=210),
                today - timedelta(days=203),
            ),
        ]
        for child, camp, start_date, end_date in camp_stays:
            CampStay.objects.update_or_create(
                child=child,
                camp=camp,
                start_date=start_date,
                defaults={"end_date": end_date},
            )

        # ------------------------------------------------------------------
        # Журнал действий
        # ------------------------------------------------------------------
        audit_rows = [
            (
                users["boss"],
                "revenue_target.update",
                "RevenueTarget",
                str(month),
                f"Сергей Андреев установил цель по выручке на {month:%m.%Y}",
            ),
            (
                users["senior"],
                "payment.create",
                "Payment",
                str(maria.pk),
                "Мария Кокорина приняла частичную оплату от Кузнецовой Марии",
            ),
            (
                users["admin"],
                "attendance.update",
                "Child",
                str(alice.pk),
                "Антон Соколов обновил отметку посещения Соколовой Алисы",
            ),
            (
                users["admin2"],
                "lead.update",
                "Lead",
                str(leads["daria"].pk),
                "Елена Романова связалась с Николаевой Дарьей",
            ),
            (
                users["boss"],
                "task.create",
                "ManagerTask",
                "demo",
                "Сергей Андреев назначил задачу администраторам",
            ),
        ]
        for actor, action, object_type, object_id, description in audit_rows:
            AuditEvent.objects.update_or_create(
                actor=actor,
                action=action,
                object_type=object_type,
                object_id=object_id,
                defaults={"description": description},
            )

        self.stdout.write(self.style.SUCCESS("Демо-данные CRM успешно созданы."))
        self.stdout.write(
            self.style.SUCCESS(
                "Логины: boss, senior, admin, admin2 · пароль: Demo12345!"
            )
        )
        self.stdout.write(
            "Сценарии: долг — Кузнецова Мария; переплата — Петрова Анна; "
            "абонемент заканчивается — Морозов Артём; занятия в долг — Лебедева Ева; "
            "истёкший trial — Фёдорова София."
        )
