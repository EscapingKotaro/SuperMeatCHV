from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models, transaction
from django.core.validators import MaxValueValidator
from django.db.models import Sum
from django.utils import timezone


TRIAL_EXPIRY_DAYS = 30


def age_label(birth_date=None, birth_year=None, age_text="", today=None):
    """Общий возраст с русскими склонениями; свободный текст сохраняется."""
    today = today or timezone.localdate()
    def plural(n, forms):
        return forms[2] if 11 <= n % 100 <= 14 else forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]
    if birth_date:
        total = max(0, (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day))
        years, months = divmod(total, 12)
    elif birth_year:
        years, months = max(0, today.year - birth_year), 0
    else:
        import re
        match = re.fullmatch(r"\s*(\d+)(?:[,.](\d{1,2}))?\s*(?:г\.?|лет|года?|месяцев)?\s*", age_text or "")
        if not match:
            return age_text or "—"
        years, months = int(match[1]), int(match[2] or 0)
        if "месяцев" in (age_text or ""):
            years, months = divmod(years, 12)
    parts = []
    if years:
        parts.append(f"{years} {plural(years, ('год', 'года', 'лет'))}")
    if months or not years:
        parts.append(f"{months} {plural(months, ('месяц', 'месяца', 'месяцев'))}")
    return " ".join(parts)


def expire_trials(today=None):
    """Идемпотентный обход всех групп. Платёж и уход блокируют одного ребёнка."""
    today = today or timezone.localdate()
    count = 0
    candidates = Child.objects.filter(
        status=Child.Status.TRIAL,
        trial_from__lte=today - timedelta(days=TRIAL_EXPIRY_DAYS),
    ).values_list("pk", flat=True)
    for pk in candidates.iterator():
        with transaction.atomic():
            child = Child.objects.select_for_update(of=("self",)).select_related("group__trainer").filter(pk=pk).first()
            if (
                not child
                or child.status != Child.Status.TRIAL
                or not child.trial_from
                or child.trial_from > today - timedelta(days=TRIAL_EXPIRY_DAYS)
                or child.payments.filter(amount__gt=0).exists()
            ):
                continue
            child.mark_as_lost(on_date=today)
            AuditEvent.objects.create(action="trial.expired", object_type="Child", object_id=str(child.pk), description=f"Пробный период истёк без оплаты: {child}")
            count += 1
    return count


class Role(models.TextChoices):
    MANAGER = "manager", "Менеджер"
    SENIOR  = "senior",  "Старший менеджер"
    BOSS    = "boss",    "Начальник"
    ADMIN    = "admin",    "Админ"

RANK = {Role.MANAGER: 0, Role.SENIOR: 1, Role.BOSS: 2, Role.ADMIN: 3}

def user_role(user):
    if user.is_superuser:
        return Role.ADMIN
    p = getattr(user, "profile", None)
    return Role(p.role) if p else Role.MANAGER


def role_rank(role):
    return RANK[Role(role)]


def user_rank(user):
    return role_rank(user_role(user))


def has_min_role(user, min_rank):
    return user_rank(user) >= min_rank


class StaffProfile(models.Model):
    """Роль пользователя (менеджер / старший / начальник / админ)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="profile", verbose_name="пользователь")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MANAGER)
    branch = models.ForeignKey("Branch", on_delete=models.SET_NULL, blank=True, null=True,
                               related_name="staff", verbose_name="филиал")
    shift_anchor = models.DateField("Первый рабочий день смены 2/2", blank=True, null=True)

def calculate_projected_end_date(group, start_date, sessions_count):
    """
    Рассчитывает дату последнего занятия по фактическому календарю группы,
    включая разовые переносы занятий.
    """
    if sessions_count <= 0 or not group:
        return None

    class_dates = effective_class_dates(
        group,
        start_date,
        start_date + timedelta(days=364),
    )
    if len(class_dates) < sessions_count:
        return None
    return class_dates[sessions_count - 1]





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

class ScheduleOverride(models.Model):
    """Разовый перенос одного занятия группы с даты на дату."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="schedule_overrides",
        verbose_name="группа",
    )
    original_date = models.DateField("Исходная дата")
    replacement_date = models.DateField("Новая дата")
    replacement_start_time = models.TimeField(
        "Новое время",
        blank=True,
        null=True,
    )
    extend_subscriptions = models.BooleanField(
        "Продлить абонементы",
        default=False,
    )
    extension_days = models.PositiveSmallIntegerField(
        "Продлено на дней",
        default=0,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="schedule_overrides_created",
        verbose_name="создал",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Перенос занятия"
        verbose_name_plural = "Переносы занятий"
        ordering = ("created_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("group", "original_date"),
                name="unique_group_schedule_override_source",
            ),
            models.UniqueConstraint(
                fields=("group", "replacement_date"),
                name="unique_group_schedule_override_target",
            ),
        ]

    def __str__(self):
        return (
            f"{self.group} · {self.original_date:%d.%m.%Y}"
            f" → {self.replacement_date:%d.%m.%Y}"
        )


def effective_class_dates(group, start_date, end_date):
    """Фактические даты занятий группы с учётом разовых переносов."""
    if not group or start_date > end_date:
        return []

    weekdays = set(
        ScheduleSlot.objects
        .filter(group=group)
        .values_list("weekday", flat=True)
    )

    dates = set()
    current = start_date
    while current <= end_date:
        if current.weekday() in weekdays:
            dates.add(current)
        current += timedelta(days=1)

    # Переносы применяются последовательно. Поэтому можно повторно перенести
    # уже перенесённое занятие: A→B, затем B→C даст только C.
    overrides = (
        ScheduleOverride.objects
        .filter(group=group)
        .order_by("created_at", "pk")
        .values_list("original_date", "replacement_date")
    )
    for original_date, replacement_date in overrides:
        dates.discard(original_date)
        dates.add(replacement_date)

    return sorted(
        class_date
        for class_date in dates
        if start_date <= class_date <= end_date
    )


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
        TRIAL    = "trial",    "Пробное (1 месяц)"
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
    certificate_ok = models.BooleanField("Справка есть", default=False)
    certificate_note = models.CharField("Комментарий к справке", max_length=255, blank=True)

    group = models.ForeignKey(Group, on_delete=models.PROTECT, blank=False,
                              related_name="children", verbose_name="группа")
    schedule = models.ManyToManyField(ScheduleSlot, blank=True, verbose_name="личный график",
                                      help_text="Пусто — ребёнок ходит по графику группы")
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    trial_from = models.DateField("Начало пробного периода", blank=True, null=True)
    discount_percent = models.PositiveSmallIntegerField("Скидка, %", default=0)
    note = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateField("Дата ухода/архива", blank=True, null=True)
    departure_group = models.ForeignKey(
        Group, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="+", verbose_name="Группа на момент ухода",
    )
    departure_trainer = models.ForeignKey(
        Trainer, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="+", verbose_name="Тренер на момент ухода",
    )


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
        cached = getattr(self, "_prefetched_objects_cache", {}).get("subscriptions")
        if cached is not None:
            return min((sub for sub in cached if sub.is_active and not sub.cancelled_at and sub.start_date <= today <= sub.end_date), key=lambda sub: sub.end_date, default=None)
        return self.subscriptions.filter(is_active=True, cancelled_at__isnull=True, start_date__lte=today, end_date__gte=today).order_by("end_date").first()

    def age_display(self):
        return age_label(self.birth_date, self.birth_year)

    def has_certificate(self):
        """Наличие справки определяется только прикреплённым файлом."""
        return bool(self.certificate)

    def sessions_left(self):
        """Остаток занятий по текущему действующему абонементу."""
        today = timezone.localdate()
        subscription = self.active_subscription()
        if not subscription:
            return 0

        cached = getattr(self, "_prefetched_objects_cache", {}).get("attendances")
        used = sum(mark.status in ("present", "absent") and subscription.start_date <= mark.date <= today for mark in cached) if cached is not None else self.attendances.filter(status__in=("present", "absent"), date__gte=subscription.start_date, date__lte=today).count()

        return max(0, subscription.sessions_total - used)

    def has_class_today(self):
        today = timezone.localdate()
        if not self.group:
            return False
        return bool(
            effective_class_dates(
                self.group,
                today,
                today,
            )
        )

    def has_mark_today(self):
        today = timezone.localdate()
        cached = getattr(self, "_prefetched_objects_cache", {}).get("attendances")
        return any(mark.date == today for mark in cached) if cached is not None else self.attendances.filter(date=today).exists()

    def projected_end_date(self):
        left = self.sessions_left()
        if left <= 0 or not self.group:
            return None

        today = timezone.localdate()
        start = today + timedelta(days=1) if self.has_mark_today() else today
        return calculate_projected_end_date(self.group, start, left)

    def sessions_left_on_date(self, target_date):
        """Остаток занятий на начало указанной даты."""
        left = self.sessions_left()
        if left <= 0 or not self.group:
            return 0

        today = timezone.localdate()
        if target_date <= today:
            return left

        class_dates = effective_class_dates(
            self.group,
            today,
            target_date - timedelta(days=1),
        )
        if self.has_mark_today() and today in class_dates:
            class_dates.remove(today)

        return max(0, left - len(class_dates))

    def debt_sessions(self):
        paid_sessions = sum(sub.sessions_total for sub in self.subscriptions.filter(cancelled_at__isnull=True))
        used_sessions = self.attendances.filter(status__in=("present", "absent")).count()
        return max(0, used_sessions - paid_sessions)

    def debt(self):
        """Денежный долг: неотменённые начисления минус реальные оплаты."""
        return max(Decimal(0), -self.balance())

    def related_total(self, relation, field, exclude_cancelled=False):
        cached = getattr(self, "_prefetched_objects_cache", {}).get(relation)
        if cached is not None:
            return sum((getattr(row, field) or Decimal(0) for row in cached if not exclude_cancelled or row.cancelled_at is None), Decimal(0))
        queryset = getattr(self, relation).all()
        if exclude_cancelled:
            queryset = queryset.filter(cancelled_at__isnull=True)
        return queryset.aggregate(total=Sum(field))["total"] or Decimal(0)

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
        return self.related_total("payments", "amount")

    def total_spent(self):
        return self.related_total("subscriptions", "price", exclude_cancelled=True)

    def balance(self):
        return self.total_paid() - self.total_spent() - self.related_total("attendances", "charge_amount")

    def is_trial_expired(self):
        """Проверяем, истёк ли месяц после пробного без оплаты."""
        if self.status != self.Status.TRIAL or not self.trial_from:
            return False
        today = timezone.localdate()
        return (today - self.trial_from).days >= TRIAL_EXPIRY_DAYS

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

    def freeze_current_history(self):
        """Фиксирует группу, тренера и ставку в старых отметках."""
        if not self.group_id:
            return

        self.attendances.filter(
            group_snapshot__isnull=True,
        ).update(
            group_snapshot=self.group,
            trainer_snapshot=self.group.trainer,
            salary_rate_snapshot=self.group.salary_rate,
        )

    def archive(self):
        self.freeze_current_history()
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.localdate()
        self.departure_group = self.group
        self.departure_trainer = self.trainer
        self.save(update_fields=[
            'status', 'archived_at', 'departure_group', 'departure_trainer',
        ])

    def mark_as_lost(self, on_date=None):
        if self.status == self.Status.LOST:
            return
        self.freeze_current_history()
        self.status = self.Status.LOST
        self.archived_at = on_date or timezone.localdate()
        self.departure_group = self.group
        self.departure_trainer = self.trainer
        self.save(update_fields=[
            'status', 'archived_at', 'departure_group', 'departure_trainer',
        ])

    def restore_from_archive(self):
        self.status = self.Status.ACTIVE
        self.archived_at = None
        self.departure_group = None
        self.departure_trainer = None
        self.save(update_fields=[
            'status', 'archived_at', 'departure_group', 'departure_trainer',
        ])


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
    promo_percent = models.PositiveSmallIntegerField("Акция, %", default=0, validators=[MaxValueValidator(100)])
    discount_percent = models.PositiveSmallIntegerField("Индивидуальная скидка на момент покупки, %", default=0, validators=[MaxValueValidator(100)])
    cancelled_at = models.DateTimeField("Отменён", null=True, blank=True)
    promo = models.CharField("Акция / промо", max_length=100, blank=True)
    promo_end_date = models.DateField("Дата окончания акции", blank=True, null=True)
    is_active = models.BooleanField("Действует", default=True)

    class Meta:
        verbose_name = "Абонемент"
        verbose_name_plural = "Абонементы"
        ordering = ("-end_date",)

    def __str__(self):
        return f"{self.child} · {self.start_date:%d.%m.%y}–{self.end_date:%d.%m.%y}"

    def cancel(self):
        if self.cancelled_at is None:
            self.is_active = False
            self.cancelled_at = timezone.now()
            self.save(update_fields=["is_active", "cancelled_at"])


def extend_subscriptions_for_schedule_move(
    group,
    original_date,
    replacement_date,
):
    """Сдвигает сроки абонементов группы на величину переноса вперёд."""
    extension_days = max(
        0,
        (replacement_date - original_date).days,
    )
    if extension_days == 0:
        return 0, 0

    subscriptions = list(
        Subscription.objects
        .select_for_update()
        .filter(
            child__group=group,
            is_active=True,
            cancelled_at__isnull=True,
            start_date__lte=original_date,
            end_date__gte=original_date,
        )
    )
    for subscription in subscriptions:
        subscription.end_date += timedelta(days=extension_days)

    if subscriptions:
        Subscription.objects.bulk_update(
            subscriptions,
            ("end_date",),
        )

    return len(subscriptions), extension_days


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

    def save(self, *args, **kwargs):
        with transaction.atomic():
            child = Child.objects.select_for_update().get(pk=self.child_id)
            super().save(*args, **kwargs)
            if Decimal(str(self.amount)) > 0 and child.status == Child.Status.TRIAL:
                Child.objects.filter(pk=child.pk).update(status=Child.Status.ACTIVE, trial_from=None)
                self.child.status = Child.Status.ACTIVE
                self.child.trial_from = None
            Newcomer.objects.filter(child_id=self.child_id).update(
                paid=Payment.objects.filter(child_id=self.child_id, amount__gt=0).exists()
            )

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
    group_snapshot = models.ForeignKey(
        Group, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="+", verbose_name="Группа на момент занятия",
    )
    trainer_snapshot = models.ForeignKey(
        Trainer, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="+", verbose_name="Тренер на момент занятия",
    )
    salary_rate_snapshot = models.DecimalField(
        "Ставка тренера на момент занятия, ₽",
        max_digits=10, decimal_places=2, blank=True, null=True,
    )
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


class CompetitionDocument(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="documents")
    child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Спортсмен (необязательно)")
    title = models.CharField("Название", max_length=200)
    file = models.FileField("Документ", upload_to="competition_documents/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


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
    group_snapshot = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        verbose_name="Группа на момент участия",
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

    def save(self, *args, **kwargs):
        # Для новых участий фиксируем группу один раз.
        # Последующий перевод ребёнка не должен менять историю соревнования.
        if (
            self._state.adding
            and self.group_snapshot_id is None
            and self.child_id
        ):
            self.group_snapshot_id = (
                Child.objects
                .filter(pk=self.child_id)
                .values_list("group_id", flat=True)
                .first()
            )

        super().save(*args, **kwargs)

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
    class Kind(models.TextChoices):
        CAMP = "camp", "Лагерь"
        TRAINING = "training", "Сборы"
    kind = models.CharField("Тип", max_length=12, choices=Kind.choices, default=Kind.CAMP)
    start_date = models.DateField("Начало", null=True, blank=True)
    end_date = models.DateField("Окончание", null=True, blank=True)
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
    resolved_at = models.DateTimeField("Закрыто", null=True, blank=True)
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

    @property
    def current_newcomer(self):
        return next(iter(self.newcomers.all()), None)

    @property
    def current_trial(self):
        return self.current_newcomer or self

    def age_display(self):
        return age_label(self.birth_date, age_text=self.age_text)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            shared = ("full_name", "birth_date", "age_text", "phone", "source")
            fields = kwargs.get("update_fields")
            values = {key: getattr(self, key) for key in shared if fields is None or key in fields}
            if values:
                self.newcomers.update(**values, updated_at=timezone.now())

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

    @property
    def application_date(self):
        return self.lead.created_at if self.lead_id else self.created_at

    def age_display(self):
        return age_label(self.birth_date, age_text=self.age_text)

    @property
    def has_paid(self):
        if not self.child_id:
            return False
        cached = getattr(self.child, "_prefetched_objects_cache", {}).get("payments")
        return any(payment.amount > 0 for payment in cached) if cached is not None else self.child.payments.filter(amount__gt=0).exists()

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.lead_id:
                Lead.objects.select_for_update().get(pk=self.lead_id)
            # paid is never accepted as manual input.
            self.paid = self.has_paid
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"paid"}
            super().save(*args, **kwargs)
            if self.lead_id:
                fields = kwargs.get("update_fields")
                shared = ("full_name", "birth_date", "age_text", "phone", "source")
                values = {key: getattr(self, key) for key in shared if fields is None or key in fields}
                if values:
                    Lead.objects.filter(pk=self.lead_id).update(**values, updated_at=timezone.now())
                    Newcomer.objects.filter(lead_id=self.lead_id).exclude(pk=self.pk).update(**values, updated_at=timezone.now())

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

    


# paid remains a compatibility cache; UI reads real Payment rows.
from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender=Payment)
def refresh_newcomer_payment_after_delete(sender, instance, **kwargs):
    Newcomer.objects.filter(child_id=instance.child_id).update(
        paid=Payment.objects.filter(child_id=instance.child_id, amount__gt=0).exists()
    )
