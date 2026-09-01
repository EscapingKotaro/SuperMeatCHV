from datetime import timedelta
from decimal import Decimal

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

    def __str__(self):
        return f"{self.user} — {self.get_role_display()}"


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

    class Meta:
        verbose_name = "Ребёнок"
        verbose_name_plural = "Дети"
        ordering = ("last_name", "first_name")

    def __str__(self):
        return f"{self.last_name} {self.first_name}"

    def age_display(self):
        """Возраст с месяцами в формате из ТЗ: 4 г. 10 мес."""
        today = timezone.localdate()
        if not self.birth_date:
            return f"{today.year - self.birth_year} лет"
        months = (today.year - self.birth_date.year) * 12 + today.month - self.birth_date.month
        if today.day < self.birth_date.day:
            months -= 1
        years, months = divmod(max(months, 0), 12)
        return f"{years} г. {months} мес."

    # ---- вычисляемые поля карточки ----
    @property
    def trainer(self):
        return self.group.trainer if self.group else None

    def active_subscription(self):
        today = timezone.localdate()
        return self.subscriptions.filter(is_active=True, start_date__lte=today, end_date__gte=today).order_by("end_date").first()

    def sessions_left(self):
        """Остаток занятий по активным абонементам («7 из 8 осталось»)."""
        sub = self.active_subscription()
        if not sub:
            return 0
        used = self.attendances.filter(
            status__in=("present", "absent"),
            date__gte=sub.start_date,
            date__lte=sub.end_date,
        ).count()
        return max(0, sub.sessions_total - used)

    def debt(self):
        """Долг = сумма абонементов − оплаты."""
        total = self.subscriptions.filter(is_active=True).aggregate(s=Sum("price"))["s"] or 0
        total += self.attendances.aggregate(s=Sum("charge_amount"))["s"] or 0
        paid = self.payments.aggregate(s=Sum("amount"))["s"] or 0
        return Decimal(total) - Decimal(paid)

    def missed_percent(self):
        present = self.attendances.filter(status="present").count()
        absent = self.attendances.filter(status="absent").count()
        total = present + absent
        return round(absent * 100 / total) if total else 0

    def nearest_expiry(self):
        sub = self.active_subscription()
        return sub.end_date if sub else None


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
    is_internal = models.BooleanField("Внутриклубные", default=True,
                                      help_text="Внутриклубные итоги попадают в карточку автоматически")

    class Meta:
        verbose_name = "Соревнование"
        verbose_name_plural = "Соревнования"
        ordering = ("-date",)

    def __str__(self):
        return f"{self.name} · {self.date:%d.%m.%y}"


class Apparatus(models.Model):
    """Снаряды соревнования (колонки таблицы как в Excel)."""
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE,
                                    related_name="apparatus", verbose_name="соревнование")
    name = models.CharField("Снаряд", max_length=100)
    order = models.PositiveSmallIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Снаряд"
        verbose_name_plural = "Снаряды"
        ordering = ("order",)

    def __str__(self):
        return self.name


class CompetitionEntry(models.Model):
    """Итог спортсмена на соревновании (в карточке ребёнка)."""
    child = models.ForeignKey(Child, on_delete=models.CASCADE,
                              related_name="competition_entries", verbose_name="ребёнок")
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE,
                                    related_name="entries", verbose_name="соревнование")
    category = models.CharField("Категория/группа", max_length=100, blank=True,
                                  help_text="Внутри категории считается место")
    rank = models.CharField("Выполняемый разряд", max_length=50, blank=True)
    place = models.PositiveSmallIntegerField("Место", blank=True, null=True)

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
        return self.scores.aggregate(s=Sum("points"))["s"] or 0

    def __str__(self):
        return f"{self.child} · {self.competition}"


class ApparatusScore(models.Model):
    entry = models.ForeignKey(CompetitionEntry, on_delete=models.CASCADE,
                              related_name="scores", verbose_name="итог")
    apparatus = models.ForeignKey(Apparatus, on_delete=models.CASCADE, verbose_name="снаряд")
    points = models.DecimalField("Баллы", max_digits=6, decimal_places=3)

    class Meta:
        verbose_name = "Балл за снаряд"
        verbose_name_plural = "Баллы за снаряды"
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "apparatus"], name="unique_entry_apparatus"
            ),
        ]

    def __str__(self):
        return f"{self.entry} · {self.apparatus} · {self.points}"


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
    """Задача менеджерам от начальника + системные напоминания."""
    title = models.CharField("Задача", max_length=255)
    description = models.TextField("Описание", blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 blank=True, null=True, related_name="tasks",
                                 verbose_name="исполнитель",
                                 help_text="Пусто — видна всем админам")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="created_tasks")
    due_date = models.DateField("Срок", blank=True, null=True)
    is_done = models.BooleanField("Выполнена", default=False)
    done_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Задача менеджеру"
        verbose_name_plural = "Задачи менеджерам"
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class Reminder(models.Model):
    """Личное напоминание администратора в календаре."""

    title = models.CharField("Напоминание", max_length=255)
    description = models.TextField("Описание", blank=True)
    remind_at = models.DateTimeField("Дата и время")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="reminders", verbose_name="исполнитель")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="created_reminders", verbose_name="создал")
    is_done = models.BooleanField("Выполнено", default=False)
    visible_to_all = models.BooleanField("Видно всей команде", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Напоминание"
        verbose_name_plural = "Напоминания"
        ordering = ("is_done", "remind_at")

    def __str__(self):
        return self.title


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
