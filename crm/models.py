from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Role(models.TextChoices):
    MANAGER = "manager", "Рядовой админ"
    SENIOR  = "senior",  "Старший админ"
    BOSS    = "boss",    "Начальник"

RANK = {Role.MANAGER: 0, Role.SENIOR: 1, Role.BOSS: 2}

def user_role(user):
    if user.is_superuser:
        return Role.BOSS
    p = getattr(user, "profile", None)
    return Role(p.role) if p else Role.MANAGER


class StaffProfile(models.Model):
    """Роль пользователя (менеджер / старший / начальник)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="profile", verbose_name="пользователь")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MANAGER)
    branch = models.ForeignKey("Branch", on_delete=models.SET_NULL, blank=True, null=True,
                               related_name="staff", verbose_name="филиал")
    shift_anchor = models.DateField("Первый рабочий день смены 2/2", blank=True, null=True)

def calculate_projected_end_date(group, start_date, sessions_count):
    """
    Рассчитывает дату последнего занятия.
    start_date — дата, с которой начинаем считать (включительно).
    """
    if sessions_count <= 0 or not group:
        return None
        
    slots = ScheduleSlot.objects.filter(group=group).order_by('weekday', 'start_time')
    if not slots.exists():
        return None
        
    current_date = start_date
    count = 0
    max_days = 365
    
    while max_days > 0:
        for slot in slots:
            if current_date.weekday() == slot.weekday:
                count += 1
                if count >= sessions_count:
                    return current_date
        current_date += timedelta(days=1)
        max_days -= 1
        
    return None





class Trainer(models.Model):
    full_name = models.CharField("ФИО", max_length=200)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    note = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Тренер"
        verbose_name_plural = "Тренеры"

    def __str__(self):
        return self.full_name


class Branch(models.Model):
    name = models.CharField("Название филиала", max_length=120, unique=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"

    def __str__(self):
        return self.name


class Group(models.Model):
    name = models.CharField("Название", max_length=100)
    trainer = models.ForeignKey(Trainer, on_delete=models.PROTECT,
                               related_name="groups", verbose_name="тренер")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, blank=True, null=True,
                               related_name="groups", verbose_name="филиал")
    single_session_price = models.DecimalField("Разовое занятие / занятие в долг, ₽",
                                               max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField("Активна", default=True)
    salary_rate = models.DecimalField("Ставка за посещение, ₽", max_digits=10, decimal_places=2, default=300)

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"

    def __str__(self):
        return self.name


class ScheduleSlot(models.Model):
    """График: слот занятия группы (день недели + время)."""
    WEEKDAYS = [(i, d) for i, d in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])]
    group = models.ForeignKey(Group, on_delete=models.CASCADE,
                              related_name="schedule", verbose_name="группа")
    weekday = models.PositiveSmallIntegerField("День недели", choices=WEEKDAYS)
    start_time = models.TimeField("Начало")
    duration_minutes = models.PositiveSmallIntegerField("Длительность, мин", default=60)

    class Meta:
        verbose_name = "Слот графика"
        verbose_name_plural = "Графики групп"

    def __str__(self):
        d = dict(self.WEEKDAYS)[self.weekday]
        return f"{self.group} · {d} {self.start_time:%H:%M}"

class SalaryAdjustment(models.Model):
    """Ручные строки ЗП: перс, замены, соревнования."""
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE,
                                related_name="salary_adjustments", verbose_name="тренер")
    month = models.DateField("Месяц", help_text="Первое число месяца")
    title = models.CharField("Назначение", max_length=200)
    amount = models.DecimalField("Сумма, ₽", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Строка ЗП"
        verbose_name_plural = "Ручные строки ЗП"

    def __str__(self):
        return f"{self.trainer} · {self.title} · {self.amount}"


class Child(models.Model):
    class Status(models.TextChoices):
        ACTIVE   = "active",   "Активный"
        TRIAL    = "trial",    "Пробное (2 недели)"
        ARCHIVED = "archived", "Архив"
        LOST     = "lost",     "Потерянный"

    last_name  = models.CharField("Фамилия", max_length=100)
    first_name = models.CharField("Имя", max_length=100)
    patronymic = models.CharField("Отчество", max_length=100, blank=True)
    birth_year = models.PositiveSmallIntegerField("Год рождения")
    birth_date = models.DateField("Дата рождения", blank=True, null=True)
    address    = models.CharField("Адрес проживания", max_length=255, blank=True)
    parent_name  = models.CharField("Родитель", max_length=200, blank=True)
    parent_phone = models.CharField("Телефон родителя", max_length=20, blank=True)
    certificate = models.ImageField("Справка (фото)", upload_to="certificates/", blank=True)
    certificate_note = models.CharField("Комментарий к справке", max_length=255, blank=True)

    group = models.ForeignKey(Group, on_delete=models.SET_NULL, blank=True, null=True,
                              related_name="children", verbose_name="группа")
    schedule = models.ManyToManyField(ScheduleSlot, blank=True, verbose_name="личный график",
                                      help_text="Пусто — ребёнок ходит по графику группы")
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    trial_from = models.DateField("Начало пробного периода", blank=True, null=True)
    discount_percent = models.PositiveSmallIntegerField("Скидка, %", default=0)
    note = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateField("Дата ухода/архива", blank=True, null=True)


    class Meta:
        verbose_name = "Ребёнок"
        verbose_name_plural = "Дети"
        ordering = ("last_name", "first_name")

    def __str__(self):
        return f"{self.last_name} {self.first_name}"


    # ---- вычисляемые поля карточки ----
    @property
    def trainer(self):
        return self.group.trainer if self.group else None

    def active_subscription(self):
        today = timezone.localdate()
        return self.subscriptions.filter(is_active=True, start_date__lte=today, end_date__gte=today).order_by("end_date").first()

    def age_display(self):
        today = timezone.localdate()

        if not self.birth_date:
            return f"{max(today.year - self.birth_year, 0)} г."

        years = today.year - self.birth_date.year
        months = today.month - self.birth_date.month

        if today.day < self.birth_date.day:
            months -= 1

        if months < 0:
            years -= 1
            months += 12

        if years == 0:
            return f"{months} мес."
        if months == 0:
            return f"{years} г."

        return f"{years} г. {months} мес."

    def has_certificate(self):
        return bool(self.certificate)

    def sessions_left(self):
        """Остаток занятий по активным абонементам."""
        today = timezone.localdate()
        left = 0

        subscriptions = self.subscriptions.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        )

        for sub in subscriptions:
            used = self.attendances.filter(
                status__in=("present", "absent"),
                date__gte=sub.start_date,
                date__lte=today,
            ).count()

            left += max(0, sub.sessions_total - used)

        return left

    def has_class_today(self):
        today = timezone.localdate()
        if not self.group:
            return False
        return ScheduleSlot.objects.filter(group=self.group, weekday=today.weekday()).exists()

    def has_mark_today(self):
        today = timezone.localdate()
        return self.attendances.filter(
            date=today, status__in=('present', 'absent')
        ).exists()

    def effective_sessions_left(self):
        left = self.sessions_left()
        if self.has_class_today() and not self.has_mark_today():
            return max(0, left - 1)
        return left

    def projected_end_date(self):
        left = self.effective_sessions_left()
        if left <= 0:
            return None
        active_sub = self.active_subscription()
        if not active_sub or not self.group:
            return None
        start = timezone.localdate()
        return calculate_projected_end_date(self.group, start, left)

    def sessions_left_on_date(self, target_date):
        left = self.effective_sessions_left()
        if left <= 0 or not self.group:
            return 0
        today = timezone.localdate()
        if target_date <= today:
            return left
        slots = ScheduleSlot.objects.filter(group=self.group)
        count = 0
        current = today + timedelta(days=1)
        while current <= target_date:
            for slot in slots:
                if current.weekday() == slot.weekday:
                    count += 1
            current += timedelta(days=1)
        return max(0, left - count)

    def debt_sessions(self):
        paid_sessions = sum(sub.sessions_total for sub in self.subscriptions.all())
        used_sessions = self.attendances.filter(status__in=("present", "absent")).count()
        return max(0, used_sessions - paid_sessions)

    def debt(self):
        """Денежный долг: начисления минус оплаты."""
        subscriptions_total = (
            self.subscriptions.aggregate(s=Sum("price"))["s"] or Decimal(0)
        )

        attendance_charges = (
            self.attendances.aggregate(s=Sum("charge_amount"))["s"] or Decimal(0)
        )

        paid = (
            self.payments.aggregate(s=Sum("amount"))["s"] or Decimal(0)
        )

        return max(
            Decimal(0),
            Decimal(subscriptions_total)
            + Decimal(attendance_charges)
            - Decimal(paid),
        )

    def missed_percent(self):
        """Процент пропущенных занятий."""
        present = self.attendances.filter(
            status="present"
        ).count()

        absent = self.attendances.filter(
            status="absent"
        ).count()

        total = present + absent

        return (
            round(absent * 100 / total)
            if total
            else 0
        )


    def nearest_expiry(self):
        """Дата окончания текущего активного абонемента."""
        sub = self.active_subscription()

        return (
            sub.end_date
            if sub
            else None
        )

    def active_promos(self):
        """Акции текущих действующих абонементов."""
        today = timezone.localdate()

        promos = []

        subscriptions = (
            self.subscriptions
            .filter(
                is_active=True,
                start_date__lte=today,
                end_date__gte=today,
            )
            .exclude(promo="")
            .order_by("promo_end_date", "end_date")
        )

        for sub in subscriptions:
            # Старые акции без отдельной даты продолжают работать:
            # для них временно используем окончание абонемента.
            promo_end = sub.promo_end_date or sub.end_date
            if promo_end >= today:
                promos.append((sub.promo, promo_end))

        return promos

    def total_paid(self):
        """Общая сумма оплат."""
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal(0)

    def total_spent(self):
        """Общая сумма абонементов."""
        return self.subscriptions.aggregate(s=Sum("price"))["s"] or Decimal(0)

    def balance(self):
        """Баланс = оплаты - абонементы - занятия в долг."""
        attendance_charges = (
            self.attendances.aggregate(s=Sum("charge_amount"))["s"] or Decimal(0)
        )
        return self.total_paid() - self.total_spent() - attendance_charges

    def is_trial_expired(self):
        """Проверяем, истёк ли пробный период (14 дней)"""
        if self.status != self.Status.TRIAL or not self.trial_from:
            return False
        today = timezone.localdate()
        return (today - self.trial_from).days >= 14

    def has_subscription_ending_soon(self):
        """Абонемент заканчивается в течение 7 дней"""
        end = self.nearest_expiry()
        if not end:
            return False
        today = timezone.localdate()
        return 0 <= (end - today).days <= 7

    def days_until_expiry(self):
        """Дней до окончания абонемента"""
        end = self.nearest_expiry()
        if not end:
            return None
        return (end - timezone.localdate()).days

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.localdate()
        self.save(update_fields=['status', 'archived_at'])

    def mark_as_lost(self):
        self.status = self.Status.LOST
        self.archived_at = timezone.localdate()
        self.save(update_fields=['status', 'archived_at'])

    def restore_from_archive(self):
        self.status = self.Status.ACTIVE
        self.archived_at = None
        self.save(update_fields=['status', 'archived_at'])


class ChildRank(models.Model):
    """Разряд идёт по годам."""
    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="ranks", verbose_name="ребёнок")
    year = models.PositiveSmallIntegerField("Год")
    rank = models.CharField("Разряд", max_length=50)

    class Meta:
        verbose_name = "Разряд"
        verbose_name_plural = "Разряды по годам"
        unique_together = ("child", "year")

    def __str__(self):
        return f"{self.child} · {self.year} · {self.rank}"


class Tariff(models.Model):
    """Шаблон абонемента, который задаёт регулярную стоимость занятий."""

    name = models.CharField("Название", max_length=120, unique=True)
    price = models.DecimalField("Стоимость, ₽", max_digits=10, decimal_places=2)
    sessions_total = models.PositiveSmallIntegerField("Количество занятий", default=8)
    duration_days = models.PositiveSmallIntegerField("Срок, дней", default=30)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"
        ordering = ("price", "name")

    def __str__(self):
        return f"{self.name} · {self.price} ₽"


class Subscription(models.Model):
    """Абонемент ребёнка."""
    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="subscriptions", verbose_name="ребёнок")
    tariff = models.ForeignKey(Tariff, on_delete=models.SET_NULL, blank=True, null=True,
                               related_name="subscriptions", verbose_name="тариф")
    start_date = models.DateField("Начало")
    end_date = models.DateField("Окончание")
    sessions_total = models.PositiveSmallIntegerField("Занятий в абонементе", default=8)
    price = models.DecimalField("Стоимость", max_digits=10, decimal_places=2)
    promo = models.CharField("Акция / промо", max_length=100, blank=True)
    promo_end_date = models.DateField("Дата окончания акции", blank=True, null=True)
    is_active = models.BooleanField("Действует", default=True)

    class Meta:
        verbose_name = "Абонемент"
        verbose_name_plural = "Абонементы"
        ordering = ("-end_date",)

    def __str__(self):
        return f"{self.child} · {self.start_date:%d.%m.%y}–{self.end_date:%d.%m.%y}"


class Payment(models.Model):
    """Оплата абонемента (из них считаем выручку и долг)."""
    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="payments", verbose_name="ребёнок")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL,
                                     blank=True, null=True, verbose_name="абонемент")
    amount = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    date = models.DateField("Дата", default=timezone.localdate)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name="принял")

    class Meta:
        verbose_name = "Оплата"
        verbose_name_plural = "Оплаты"
        ordering = ("-date",)

    def __str__(self):
        return f"{self.child} · {self.amount} · {self.date:%d.%m.%y}"


class Attendance(models.Model):
    """Табель отметок: плюс / пропуск / заморозка / отпуск / уважительная."""
    class Status(models.TextChoices):
        PRESENT  = "present",  "✅ Посещение"
        ABSENT   = "absent",   "🟥 Пропуск"
        EXCUSED  = "excused",  "Пропуск по уважительной (сдвигает окончание)"
        FROZEN   = "frozen",   "🟦 Заморозка"
        VACATION = "vacation", "🟨 Отпуск"

    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="attendances", verbose_name="ребёнок")
    date = models.DateField("Дата")
    slot = models.ForeignKey(ScheduleSlot, on_delete=models.SET_NULL,
                             blank=True, null=True, verbose_name="слот")
    status = models.CharField("Отметка", max_length=10, choices=Status.choices, default=Status.PRESENT)
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    charge_amount = models.DecimalField("Начислено за занятие в долг, ₽",
                                        max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Посещение"
        verbose_name_plural = "Посещения"
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["child", "date", "slot"], name="one_mark_per_slot"),
        ]

    def __str__(self):
        return f"{self.child} · {self.date:%d.%m.%y} · {self.get_status_display()}"


class Competition(models.Model):
    name = models.CharField("Название", max_length=200)
    date = models.DateField("Дата")
    city = models.CharField("Город", max_length=100, blank=True)
    is_internal = models.BooleanField(
        "Внутриклубное",
        default=True,
        help_text="Снимите флажок, если соревнование выездное",
    )

    class Meta:
        verbose_name = "Соревнование"
        verbose_name_plural = "Соревнования"
        ordering = ("-date",)

    def __str__(self):
        return f"{self.name} · {self.date:%d.%m.%y}"


class Apparatus(models.Model):
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="apparatus",
        verbose_name="соревнование",
    )
    name = models.CharField("Дисциплина", max_length=100)

    # Техническое поле. Пользователь его не заполняет.
    order = models.PositiveSmallIntegerField(
        "Порядок",
        default=0,
    )

    class Meta:
        verbose_name = "Дисциплина"
        verbose_name_plural = "Дисциплины"
        ordering = ("order", "pk")

    def __str__(self):
        return self.name


class CompetitionEntry(models.Model):
    child = models.ForeignKey(
        Child,
        on_delete=models.CASCADE,
        related_name="competition_entries",
        verbose_name="ребёнок",
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name="соревнование",
    )
    category = models.CharField(
        "Категория/группа",
        max_length=100,
        blank=True,
        help_text="Внутри категории считается место",
    )
    rank = models.CharField(
        "Выполняемый разряд",
        max_length=50,
        blank=True,
    )
    place = models.PositiveSmallIntegerField(
        "Место",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Итог соревнования"
        verbose_name_plural = "Итоги соревнований"
        constraints = [
            models.UniqueConstraint(
                fields=["child", "competition", "category"],
                name="unique_child_competition_category",
            ),
        ]

    def total_points(self):
        apparatus_ids = list(
            self.competition.apparatus.values_list(
                "id",
                flat=True,
            )
        )

        if not apparatus_ids:
            return None

        scores = list(
            self.scores.filter(
                apparatus_id__in=apparatus_ids,
            )
        )

        if len(scores) != len(apparatus_ids):
            return None

        if any(score.points is None for score in scores):
            return None

        return sum(
            (score.points for score in scores),
            Decimal("0"),
        )

    def scores_complete(self):
        return self.total_points() is not None

    def __str__(self):
        return f"{self.child} · {self.competition}"


class ApparatusScore(models.Model):
    entry = models.ForeignKey(
        CompetitionEntry,
        on_delete=models.CASCADE,
        related_name="scores",
        verbose_name="итог",
    )
    apparatus = models.ForeignKey(
        Apparatus,
        on_delete=models.CASCADE,
        verbose_name="дисциплина",
    )
    points = models.DecimalField(
        "Баллы",
        max_digits=12,
        decimal_places=3,
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Балл за дисциплину"
        verbose_name_plural = "Баллы за дисциплины"
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "apparatus"],
                name="unique_entry_apparatus",
            ),
        ]

    def __str__(self):
        value = "—" if self.points is None else self.points
        return f"{self.entry} · {self.apparatus} · {value}"

def recalculate_competition_places(competition):
    categories = (
        competition.entries
        .values_list("category", flat=True)
        .distinct()
    )

    for category in categories:
        entries = list(
            competition.entries
            .filter(category=category)
            .select_related("competition")
        )

        completed = []

        for entry in entries:
            total = entry.total_points()

            if total is None:
                CompetitionEntry.objects.filter(
                    pk=entry.pk,
                ).update(place=None)

                entry.place = None
                continue

            completed.append((entry, total))

        completed.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        last_total = None
        last_place = 0

        for index, (entry, total) in enumerate(
            completed,
            start=1,
        ):
            if last_total is not None and total == last_total:
                place = last_place
            else:
                place = index

            CompetitionEntry.objects.filter(
                pk=entry.pk,
            ).update(place=place)

            entry.place = place
            last_total = total
            last_place = place

class Camp(models.Model):
    name = models.CharField("Название лагеря", max_length=200)

    class Meta:
        verbose_name = "Лагерь"
        verbose_name_plural = "Лагеря"

    def __str__(self):
        return self.name


class CampStay(models.Model):
    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="camp_stays", verbose_name="ребёнок")
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, verbose_name="лагерь")
    start_date = models.DateField("Начало")
    end_date = models.DateField("Окончание")

    class Meta:
        verbose_name = "Поездка в лагерь"
        verbose_name_plural = "Лагеря (поездки)"

    def __str__(self):
        return f"{self.child} · {self.camp}"


class Expense(models.Model):
    """Бытовые расходы (вода и т.п.) — заполняют админы."""
    class Category(models.TextChoices):
        HOUSEHOLD = "household", "Бытовые товары"
        EQUIPMENT = "equipment", "Инвентарь"
        REPAIR = "repair", "Ремонт"
        OTHER = "other", "Другое"

    title = models.CharField("Назначение", max_length=200)
    category = models.CharField(
        "Категория", max_length=20, choices=Category.choices, default=Category.HOUSEHOLD
    )
    amount = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    date = models.DateField("Дата", default=timezone.localdate)
    receipt = models.FileField("Чек", upload_to="expense_receipts/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name="создал")

    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ("-date",)

    def __str__(self):
        return f"{self.title} · {self.amount}"


class RevenueTarget(models.Model):
    """Цель по выручке — ставит только начальник."""
    month = models.DateField("Месяц", unique=True, help_text="Первое число месяца")
    amount = models.DecimalField("Цель, ₽", max_digits=12, decimal_places=2)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                               null=True, blank=True, verbose_name="установил")

    class Meta:
        verbose_name = "Цель по выручке"
        verbose_name_plural = "Цели по выручке"

    def __str__(self):
        return f"{self.month:%B %Y} · {self.amount}"


class SalaryPayout(models.Model):
    """ЗП тренера одной цифрой за месяц (вести детально не нужно)."""
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE,
                                related_name="payouts", verbose_name="тренер")
    month = models.DateField("Месяц", help_text="Первое число месяца")
    amount = models.DecimalField("Выплачено, ₽", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Выплата ЗП"
        verbose_name_plural = "ЗП тренеров"
        unique_together = ("trainer", "month")

    def __str__(self):
        return f"{self.trainer} · {self.month:%B %Y} · {self.amount}"


class ManagerTask(models.Model):
    """Единая задача CRM: руководитель, календарь и уведомления."""

    title = models.CharField(
        "Задача",
        max_length=255,
    )

    description = models.TextField(
        "Описание",
        blank=True,
    )

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tasks",
        verbose_name="Исполнитель",
        help_text="Пусто — общая задача для всей администрации",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
        verbose_name="Автор",
    )

    # Крайний срок выполнения задачи.
    due_date = models.DateField(
        "Крайний срок",
        blank=True,
        null=True,
    )

    # Конкретная дата/время, на которой задача размещается в календаре.
    # Если поле пустое, позже календарь будет использовать due_date.
    scheduled_at = models.DateTimeField(
        "Дата и время в календаре",
        blank=True,
        null=True,
    )
    
    scheduled_end_at = models.DateTimeField(
    "Окончание в календаре",
    blank=True,
    null=True,
)

    is_done = models.BooleanField(
        "Выполнена",
        default=False,
    )

    done_at = models.DateTimeField(
        "Выполнена в",
        blank=True,
        null=True,
    )

    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="completed_tasks",
        verbose_name="Выполнил",
    )

    completion_comment = models.TextField(
        "Комментарий при выполнении",
        blank=True,
    )

    created_at = models.DateTimeField(
        "Создана",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

class Notification(models.Model):
    class Kind(models.TextChoices):
        TASK_CREATED = "task_created", "Новая задача"
        TASK_UPDATED = "task_updated", "Задача изменена"
        TASK_COMPLETED = "task_completed", "Задача выполнена"
        TASK_REOPENED = "task_reopened", "Задача возвращена"
        TASK_DELETED = "task_deleted", "Задача удалена"
        LEAD_CREATED = "lead_created", "Новая заявка"
        TRIAL_SCHEDULED = "trial_scheduled", "Пробное занятие"
        SUBSCRIPTION_EXPIRING = "subscription_expiring", "Заканчивается абонемент"
        SUBSCRIPTION_DEBT = "subscription_debt", "Абонемент закончился — есть долг"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notifications", verbose_name="Получатель",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="triggered_notifications",
        verbose_name="Инициатор",
    )
    task = models.ForeignKey(
        ManagerTask, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="notifications",
        verbose_name="Задача",
    )
    kind = models.CharField("Тип", max_length=30, choices=Kind.choices)
    message = models.CharField("Текст", max_length=500)
    url = models.CharField("Ссылка", max_length=500, blank=True)
    event_key = models.CharField(
        "Ключ события", max_length=160, blank=True, null=True,
    )
    read_at = models.DateTimeField("Прочитано", null=True, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("recipient", "read_at"))]
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "event_key"),
                name="unique_notification_event",
            ),
        ]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

    def __str__(self):
        return self.message

class Lead(models.Model):
    """Заявка из рекламы, звонка или сайта. Не обязана стать новичком."""

    class Status(models.TextChoices):
        NEW = "new", "Новая заявка"
        CONTACTED = "contacted", "Связались"
        QUALIFIED = "qualified", "Подходит"
        LOST = "lost", "Закрыта"

    full_name = models.CharField("ФИО", max_length=220)
    birth_date = models.DateField("Дата рождения", blank=True, null=True)
    age_text = models.CharField("Возраст", max_length=30, blank=True)
    source = models.CharField("Источник", max_length=100, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    trial_at = models.DateTimeField("Пробное занятие", blank=True, null=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, blank=True, null=True,
                                related_name="leads", verbose_name="тренер")
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, blank=True, null=True,
                              related_name="leads", verbose_name="группа")
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.NEW)
    comment = models.TextField("Комментарий", blank=True)
    imported_from_ad = models.BooleanField("Автоматически из рекламы", default=False)
    child = models.OneToOneField(Child, on_delete=models.SET_NULL, blank=True, null=True,
                                 related_name="source_lead", verbose_name="карточка спортсмена")
    created_at = models.DateTimeField("Дата заявки", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        ordering = ("-created_at",)

    def __str__(self):
        return self.full_name


class Newcomer(models.Model):
    """Отдельная операционная таблица пробных занятий."""

    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, blank=True, null=True,
                             related_name="newcomers", verbose_name="исходная заявка")
    full_name = models.CharField("ФИО", max_length=220)
    birth_date = models.DateField("Дата рождения", blank=True, null=True)
    age_text = models.CharField("Возраст", max_length=30, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    source = models.CharField("Источник", max_length=100, blank=True)
    trial_at = models.DateTimeField("Дата и время пробного", blank=True, null=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, blank=True, null=True,
                                related_name="newcomers", verbose_name="тренер")
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, blank=True, null=True,
                              related_name="newcomers", verbose_name="группа")
    attended = models.BooleanField("Был на пробном", default=False)
    paid = models.BooleanField("Оплатил", default=False)
    lesson_cancelled = models.BooleanField("Занятие отменено", default=False)
    comment = models.TextField("Комментарий / перенос", blank=True)
    child = models.OneToOneField(Child, on_delete=models.SET_NULL, blank=True, null=True,
                                 related_name="source_newcomer", verbose_name="карточка спортсмена")
    created_at = models.DateTimeField("Добавлен", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Новичок"
        verbose_name_plural = "Новички"
        ordering = ("-created_at",)

    def __str__(self):
        return self.full_name


class AuditEvent(models.Model):
    """Журнал действий в пользовательском интерфейсе CRM."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_audit_events",
        verbose_name="пользователь",
    )
    action = models.CharField("действие", max_length=100)
    object_type = models.CharField("тип объекта", max_length=100, blank=True)
    object_id = models.CharField("ID объекта", max_length=64, blank=True)
    description = models.CharField("описание", max_length=500)
    created_at = models.DateTimeField("время", auto_now_add=True)

    class Meta:
        verbose_name = "Событие журнала"
        verbose_name_plural = "Журнал действий"
        ordering = ("-created_at",)

    def __str__(self):
        return self.description


class User(AbstractUser):
    def __str__(self):
        return self.get_full_name() or self.username

    