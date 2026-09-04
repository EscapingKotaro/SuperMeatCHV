from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model, admin as auth_admin
from django.http import HttpResponse
from django.db.models import Count, Q, Sum
from django.utils import timezone
from openpyxl import Workbook

from .models import *
from .models import user_role, Role, RANK


def xlsx_response(headers, rows, filename):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(resp)
    return resp


class RoleGate(admin.ModelAdmin):
    """min_level: 0 — все админы, 1 — старший+, 2 — только начальник."""
    min_level = 0

    def get_model_perms(self, request):
        if RANK[user_role(request.user)] < self.min_level:
            return {}
        return super().get_model_perms(request)


# ---------- Пользователи и роли ----------
class ProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    verbose_name = "Роль в CRM"

class UserAdmin(auth_admin.UserAdmin):
    inlines = (ProfileInline,)
    list_display = ("username", "first_name", "last_name", "is_staff", "get_role")

    @admin.display(description="Роль")
    def get_role(self, obj):
        return user_role(obj).label

admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), UserAdmin)


# ---------- Логи: начальник видит логи всех, остальные — нет ----------
class LogEntryAdmin(RoleGate, admin.ModelAdmin):
    min_level = 2   # только boss
    list_display = ("action_time", "user", "content_type", "object_repr", "action_flag")
    list_filter = ("user", "content_type")
    search_fields = ("object_repr",)

if admin.site.is_registered(LogEntry):
    admin.site.unregister(LogEntry)
admin.site.register(LogEntry, LogEntryAdmin)


# ---------- Дети ----------
class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0

class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("date", "amount", "subscription", "created_by")

class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 1
    fields = ("date", "status", "comment")
    ordering = ("-date",)

class RankInline(admin.TabularInline):
    model = ChildRank
    extra = 0

class CompetitionEntryInline(admin.TabularInline):
    model = CompetitionEntry
    extra = 0
    fields = ("competition", "category", "rank", "place")

class CampStayInline(admin.TabularInline):
    model = CampStay
    extra = 0


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = (
        "full",
        "birth_date",
        "group",
        "trainer",
        "status",
        "left",
        "debt_col",
        "expiry_col",
        "discount_percent",
        "tags",
    )
    list_display_links = ("full",)

    list_filter = (
        "status",
        "group",
        "group__trainer",
        "trial_from",
    )

    search_fields = (
        "last_name",
        "first_name",
        "patronymic",
        "parent_name",
        "parent_phone",
    )

    autocomplete_fields = ["group"]
    ordering = ("last_name", "first_name")

    actions = (
        "to_archive",
        "to_lost",
        "to_active",
    )

    inlines = [
    SubscriptionInline,
    PaymentInline,
    AttendanceInline,
    RankInline,
    CompetitionEntryInline,
    CampStayInline,
]

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "last_name",
                    "first_name",
                    "patronymic",
                    "birth_date",
                    "status",
                    "group",
                )
            },
        ),
        (
            "Контакты",
            {
                "fields": (
                    "parent_name",
                    "parent_phone",
                    "address",
                )
            },
        ),
        (
            "Справка",
            {
                "fields": (
                    "certificate",
                    "certificate_note",
                )
            },
        ),
        (
            "Прочее",
            {
                "fields": (
                    "trial_from",
                    "discount_percent",
                    "note",
                    "schedule",
                )
            },
        ),
    )

    filter_horizontal = ("schedule",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            attended=Count(
                "attendances",
                filter=Q(attendances__status="present"),
            )
        )

    @admin.display(description="Ребёнок")
    def full(self, obj):
        return f"{obj.last_name} {obj.first_name}"

    @admin.display(description="Осталось занятий")
    def left(self, obj):
        sub = obj.active_subscription()
        if not sub:
            return "—"

        return f"{obj.sessions_left()} из {sub.sessions_total} осталось"

    @admin.display(description="Долг")
    def debt_col(self, obj):
        debt = obj.debt()
        return f"💰 {debt}" if debt > 0 else "—"

    @admin.display(description="Окончание абонемента")
    def expiry_col(self, obj):
        expiry = obj.nearest_expiry()

        if not expiry:
            return "—"

        days = (expiry - timezone.localdate()).days
        flag = "🟥" if days <= 7 else "🟩"

        return f"{flag} {expiry:%d.%m} ({days} дн)"

    @admin.display(description="Метки")
    def tags(self, obj):
        tags = []

        if obj.certificate:
            tags.append("📄 справка")

        if obj.status == Child.Status.TRIAL:
            tags.append("🟪 пробное")

        return " ".join(tags)

    @admin.action(description="🗄 В архив")
    def to_archive(self, request, queryset):
        queryset.update(status=Child.Status.ARCHIVED)

    @admin.action(description="😴 В потерянные")
    def to_lost(self, request, queryset):
        queryset.update(status=Child.Status.LOST)

    @admin.action(description="✅ В активные")
    def to_active(self, request, queryset):
        queryset.update(status=Child.Status.ACTIVE)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "trainer", "single_session_price", "children_count", "is_active")
    list_filter = ("branch", "trainer", "is_active")
    search_fields = ("name",)
    inlines = (ScheduleSlotInline := type("ScheduleSlotInline", (admin.TabularInline,),
                 {"model": ScheduleSlot, "extra": 1}),)

    @admin.display(description="Детей")
    def children_count(self, obj):
        return obj.children.filter(status__in=("active", "trial")).count()


@admin.register(Trainer)
class TrainerAdmin(RoleGate):
    min_level = 0
    list_display = ("full_name", "phone", "is_active", "groups_list")
    search_fields = ("full_name",)

    @admin.display(description="Группы")
    def groups_list(self, obj):
        return ", ".join(g.name for g in obj.groups.all())


@admin.register(StaffProfile)
class StaffProfileAdmin(RoleGate):
    min_level = 1
    list_display = ("user", "role", "branch", "shift_anchor")
    list_filter = ("role", "branch")
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = ("group", "weekday", "start_time", "duration_minutes")
    list_filter = ("group", "weekday")
    ordering = ("group", "weekday", "start_time")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("child", "date", "status", "charge_amount", "comment")
    list_filter = ("status", "date", "child__group")
    search_fields = ("child__last_name", "child__first_name")
    date_hierarchy = "date"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("child", "tariff", "start_date", "end_date", "sessions_total", "price", "is_active")
    list_filter = ("is_active", "tariff", "start_date", "end_date")
    search_fields = ("child__last_name", "child__first_name")


@admin.register(ChildRank)
class ChildRankAdmin(admin.ModelAdmin):
    list_display = ("child", "year", "rank")
    list_filter = ("year", "rank")
    search_fields = ("child__last_name", "child__first_name")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "is_active")


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "sessions_total", "duration_days", "is_active")
    list_filter = ("is_active",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "source", "status", "imported_from_ad", "created_at")
    list_filter = ("status", "imported_from_ad", "source")
    search_fields = ("full_name", "phone", "comment")


@admin.register(Newcomer)
class NewcomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "trial_at", "attended", "paid", "lesson_cancelled", "child")
    list_filter = ("attended", "paid", "lesson_cancelled", "trainer")
    search_fields = ("full_name", "phone", "comment")


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "remind_at", "assignee", "visible_to_all", "is_done")
    list_filter = ("is_done", "visible_to_all", "assignee")


# ---------- Финансы: рядовой НЕ видит KPI и ЗП ----------
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("date", "child", "amount", "created_by")
    list_filter = ("date",)
    search_fields = ("child__last_name",)

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "category", "amount", "created_by")
    list_filter = ("date", "category")

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AuditEvent)
class AuditEventAdmin(RoleGate):
    min_level = 2
    list_display = ("created_at", "actor", "action", "description")
    list_filter = ("action", "created_at")
    search_fields = ("description", "actor__username")
    readonly_fields = ("actor", "action", "object_type", "object_id", "description", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RevenueTarget)
class RevenueTargetAdmin(RoleGate):
    min_level = 2   # ставит только начальник
    list_display = ("month", "amount", "set_by")

    def save_model(self, request, obj, form, change):
        obj.set_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SalaryPayout)
class SalaryPayoutAdmin(RoleGate):
    min_level = 1   # старший и начальник
    list_display = ("trainer", "month", "amount")
    list_filter = ("month", "trainer")
    actions = ("export_xlsx",)

    @admin.action(description="📥 Экспорт в Excel")
    def export_xlsx(self, request, queryset):
        rows = queryset.values_list("trainer__full_name", "month", "amount")
        return xlsx_response(["Тренер", "Месяц", "Сумма"], rows, "salary")


# ---------- Соревнования ----------
class ApparatusInline(admin.TabularInline):
    model = Apparatus
    extra = 2

class ScoresInline(admin.TabularInline):
    model = ApparatusScore
    extra = 3

class EntriesInline(admin.TabularInline):
    model = CompetitionEntry
    extra = 1
    fields = ("child", "category", "rank", "place")


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "city", "is_internal")
    list_filter = ("is_internal",)
    search_fields = ("name",)
    inlines = (ApparatusInline, EntriesInline)
    actions = ("recalc_places", "export_xlsx")

    @admin.action(description="🏆 Пересчитать места в категориях")
    def recalc_places(self, request, queryset):
        for comp in queryset:
            cats = comp.entries.values_list("category", flat=True).distinct()
            for cat in cats:
                entries = (comp.entries.filter(category=cat)
                           .annotate(total=Sum("scores__points"))
                           .order_by("-total"))
                for i, e in enumerate(entries, 1):
                    CompetitionEntry.objects.filter(pk=e.pk).update(place=i)

    @admin.action(description="📥 Таблица результатов в Excel")
    def export_xlsx(self, request, queryset):
        for comp in queryset:
            headers = ["Спортсмен", "Год рожд.", "Разряд", "Категория"] + \
                      [a.name for a in comp.apparatus.all()] + ["Сумма", "Место"]
            rows = []
            for e in comp.entries.select_related("child").prefetch_related("scores"):
                scores = {s.apparatus_id: s.points for s in e.scores.all()}
                rows.append(
                    [str(e.child), e.child.birth_year, e.rank, e.category] +
                    [scores.get(a.id, "") for a in comp.apparatus.all()] +
                    [float(e.total_points()), e.place or ""])
            return xlsx_response(headers, rows, f"competition_{comp.pk}")


@admin.register(Apparatus)
class ApparatusAdmin(admin.ModelAdmin):
    list_display = ("competition", "name", "order")
    list_filter = ("competition",)
    search_fields = ("name", "competition__name")


@admin.register(CompetitionEntry)
class CompetitionEntryAdmin(admin.ModelAdmin):
    list_display = ("child", "competition", "category", "rank", "place")
    list_filter = ("competition", "category")
    search_fields = ("child__last_name", "child__first_name", "competition__name")


@admin.register(ApparatusScore)
class ApparatusScoreAdmin(admin.ModelAdmin):
    list_display = ("entry", "apparatus", "points")
    list_filter = ("apparatus__competition", "apparatus")


@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(CampStay)
class CampStayAdmin(admin.ModelAdmin):
    list_display = ("child", "camp", "start_date", "end_date")
    list_filter = ("camp", "start_date")


@admin.register(ManagerTask)
class ManagerTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "assignee", "due_date", "is_done", "created_by")
    list_filter = ("is_done", "assignee", "due_date")
    search_fields = ("title", "description", "assignee__username", "created_by__username")
    autocomplete_fields = ["assignee", "created_by"]
    ordering = ("-created_at",)
