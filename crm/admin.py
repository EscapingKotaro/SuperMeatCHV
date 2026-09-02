from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from .models import (
    StaffProfile, Trainer, Group, ScheduleSlot, Child, ChildRank,
    Subscription, Payment, Attendance, Competition, Apparatus,
    CompetitionEntry, ApparatusScore, Camp, CampStay, Expense,
    RevenueTarget, SalaryPayout, ManagerTask,
)

User = get_user_model()


# ========== Пользователь и профиль ==========
class StaffProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    verbose_name_plural = "Профиль сотрудника"
    fk_name = "user"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Дополнительно", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Дополнительно", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)
    inlines = [StaffProfileInline]


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ["user"]


# ========== Тренеры и группы ==========
class ScheduleSlotInline(admin.TabularInline):
    model = ScheduleSlot
    extra = 1
    fields = ("weekday", "start_time", "duration_minutes")
    ordering = ("weekday", "start_time")


@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("full_name", "phone")
    ordering = ("full_name",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "trainer", "is_active")
    list_filter = ("is_active", "trainer")
    search_fields = ("name", "trainer__full_name")
    autocomplete_fields = ["trainer"]
    inlines = [ScheduleSlotInline]


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = ("group", "weekday", "start_time", "duration_minutes")
    list_filter = ("weekday",)
    search_fields = ("group__name",)
    autocomplete_fields = ["group"]
    ordering = ("weekday", "start_time")


# ========== Дети ==========
class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 1
    fields = ("start_date", "end_date", "sessions_total", "price", "promo")
    ordering = ("-end_date",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1
    fields = ("amount", "date", "subscription", "created_by")
    readonly_fields = ("created_by",)


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 1
    fields = ("date", "slot", "status", "comment")
    ordering = ("-date",)


class ChildRankInline(admin.TabularInline):
    model = ChildRank
    extra = 1
    fields = ("year", "rank")


class CompetitionEntryInline(admin.TabularInline):
    model = CompetitionEntry
    extra = 0
    fields = ("competition", "category", "rank", "place")
    readonly_fields = ("competition",)


class CampStayInline(admin.TabularInline):
    model = CampStay
    extra = 1
    fields = ("camp", "start_date", "end_date")


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = (
        "last_name", "first_name", "patronymic", "birth_year","birth_date",
        "parent_name", "parent_phone", "group", "status", "debt",
    )
    list_filter = ("status", "group", "birth_year", "trial_from")
    search_fields = ("last_name", "first_name", "patronymic", "parent_name", "parent_phone")
    autocomplete_fields = ["group"]
    ordering = ("last_name", "first_name")
    inlines = [
        SubscriptionInline,
        PaymentInline,
        AttendanceInline,
        ChildRankInline,
        CompetitionEntryInline,
        CampStayInline,
    ]
    fieldsets = (
        ("Основное", {
            "fields": ("last_name", "first_name", "patronymic", "birth_year","birth_date", "status", "group")
        }),
        ("Контакты", {
            "fields": ("parent_name", "parent_phone", "address")
        }),
        ("Справка", {
            "fields": ("certificate", "certificate_note")
        }),
        ("Прочее", {
            "fields": ("trial_from", "discount_percent", "note", "schedule")
        }),
    )
    filter_horizontal = ("schedule",)


# ========== Абонементы, оплаты, посещения ==========
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("child", "start_date", "end_date", "sessions_total", "price", "promo")
    list_filter = ("promo", "start_date", "end_date")
    search_fields = ("child__last_name", "child__first_name", "promo")
    autocomplete_fields = ["child"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("child", "amount", "date", "subscription", "created_by")
    list_filter = ("date", "subscription")
    search_fields = ("child__last_name", "child__first_name")
    autocomplete_fields = ["child", "subscription", "created_by"]
    ordering = ("-date",)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("child", "date", "slot", "status", "comment")
    list_filter = ("status", "date", "slot__group")
    search_fields = ("child__last_name", "child__first_name")
    autocomplete_fields = ["child", "slot"]
    ordering = ("-date",)


# ========== Разряды ==========
@admin.register(ChildRank)
class ChildRankAdmin(admin.ModelAdmin):
    list_display = ("child", "year", "rank")
    list_filter = ("year", "rank")
    search_fields = ("child__last_name", "child__first_name")
    autocomplete_fields = ["child"]


# ========== Соревнования ==========
class ApparatusInline(admin.TabularInline):
    model = Apparatus
    extra = 4
    fields = ("name", "order")


class ApparatusScoreInline(admin.TabularInline):
    model = ApparatusScore
    extra = 0
    fields = ("apparatus", "points")
    autocomplete_fields = ["apparatus"]


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "city", "is_internal")
    list_filter = ("is_internal", "date", "city")
    search_fields = ("name", "city")
    ordering = ("-date",)
    inlines = [ApparatusInline, CompetitionEntryInline]


@admin.register(Apparatus)
class ApparatusAdmin(admin.ModelAdmin):
    list_display = ("competition", "name", "order")
    list_filter = ("competition",)
    search_fields = ("name", "competition__name")
    autocomplete_fields = ["competition"]
    ordering = ("competition", "order")


@admin.register(CompetitionEntry)
class CompetitionEntryAdmin(admin.ModelAdmin):
    list_display = ("child", "competition", "category", "rank", "place", "total_points")
    list_filter = ("competition", "category", "rank")
    search_fields = ("child__last_name", "child__first_name", "competition__name")
    autocomplete_fields = ["child", "competition"]
    inlines = [ApparatusScoreInline]


@admin.register(ApparatusScore)
class ApparatusScoreAdmin(admin.ModelAdmin):
    list_display = ("entry", "apparatus", "points")
    search_fields = ("entry__child__last_name", "apparatus__name")
    autocomplete_fields = ["entry", "apparatus"]


# ========== Лагеря ==========
@admin.register(Camp)
class CampAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(CampStay)
class CampStayAdmin(admin.ModelAdmin):
    list_display = ("child", "camp", "start_date", "end_date")
    list_filter = ("camp", "start_date", "end_date")
    search_fields = ("child__last_name", "child__first_name", "camp__name")
    autocomplete_fields = ["child", "camp"]


# ========== Финансы и задачи ==========
@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "amount", "date", "created_by")
    list_filter = ("date", "created_by")
    search_fields = ("title",)
    autocomplete_fields = ["created_by"]
    ordering = ("-date",)


@admin.register(RevenueTarget)
class RevenueTargetAdmin(admin.ModelAdmin):
    list_display = ("month", "amount", "set_by")
    list_filter = ("month", "set_by")
    search_fields = ("set_by__username",)
    autocomplete_fields = ["set_by"]


@admin.register(SalaryPayout)
class SalaryPayoutAdmin(admin.ModelAdmin):
    list_display = ("trainer", "month", "amount")
    list_filter = ("month", "trainer")
    search_fields = ("trainer__full_name",)
    autocomplete_fields = ["trainer"]


@admin.register(ManagerTask)
class ManagerTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "assignee", "due_date", "is_done", "created_by", "created_at")
    list_filter = ("is_done", "assignee", "due_date")
    search_fields = ("title", "description", "assignee__username", "created_by__username")
    autocomplete_fields = ["assignee", "created_by"]
    ordering = ("-created_at",)