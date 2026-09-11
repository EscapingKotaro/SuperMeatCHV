from datetime import timedelta
from decimal import Decimal

from django.forms import inlineformset_factory
from django import forms
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from .models import (
    Apparatus,
    Camp,
    Child,
    ChildGroupMembership,
    Competition,
    CompetitionEntry,
    Expense,
    Lead,
    ManagerTask,
    Newcomer,
    RevenueTarget,
    Role,
    SalaryAdjustment,
    StaffProfile,
    Subscription,
    Tariff,
    Group,
    Trainer,
    ScheduleSlot,
    role_rank,
    user_rank,
)


class StyledFormMixin:
    def apply_styles(self):
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "h-4 w-4 rounded border-slate-300"
            else:
                field.widget.attrs["class"] = "field"


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ("title", "category", "amount", "date", "receipt")
        widgets = {"date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        self.apply_styles()


class SalaryAdjustmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SalaryAdjustment
        fields = ("trainer", "title", "amount")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["trainer"].queryset = Trainer.objects.filter(
            is_active=True,
        ).order_by("full_name")
        self.apply_styles()


class ManagerTaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ManagerTask
        fields = (
            "title",
            "description",
            "assignee",
            "scheduled_at",
            "scheduled_end_at",
            "due_date",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "scheduled_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "scheduled_end_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "due_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        user_model = get_user_model()

        self.fields["assignee"].queryset = (
            user_model.objects
            .filter(is_active=True, is_staff=True)
            .exclude(profile__role=Role.BOSS)
            .order_by("first_name", "last_name", "username")
        )

        self.fields["assignee"].required = False
        self.fields["assignee"].empty_label = (
            "Общая задача для администрации"
        )

        self.fields["scheduled_at"].required = False
        self.fields["scheduled_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
        ]

        self.fields["scheduled_end_at"].required = False
        self.fields["scheduled_end_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
        ]

        self.fields["due_date"].required = False
        self.fields["due_date"].input_formats = [
            "%Y-%m-%d",
        ]

        self.apply_styles()

    def clean(self):
        cleaned = super().clean()

        start_at = cleaned.get("scheduled_at")
        end_at = cleaned.get("scheduled_end_at")

        if end_at and not start_at:
            self.add_error(
                "scheduled_end_at",
                "Сначала укажите дату и время начала задачи",
            )

        elif start_at and end_at and end_at <= start_at:
            self.add_error(
                "scheduled_end_at",
                "Окончание должно быть позже начала",
            )

        return cleaned


class RevenueTargetForm(StyledFormMixin, forms.ModelForm):
    month = forms.DateField(
        label="Месяц",
        input_formats=["%Y-%m", "%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
    )

    class Meta:
        model = RevenueTarget
        fields = ("month", "amount")

    def clean_month(self):
        value = self.cleaned_data["month"]
        return value.replace(day=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class CompetitionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Competition
        fields = ("name", "date", "city", "is_internal")
        widgets = {"date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        self.apply_styles()


class CompetitionEntryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CompetitionEntry
        fields = ("child", "category", "rank", "place")

    def __init__(self, *args, competition=None, **kwargs):
        super().__init__(*args, **kwargs)
        if competition is None and getattr(self.instance, "competition_id", None):
            competition = self.instance.competition

        # Во внутриклубном соревновании место считается автоматически.
        # Для выездного его можно внести вручную или импортировать из Excel.
        if competition and competition.is_internal:
            self.fields.pop("place", None)

        self.apply_styles()


class StaffCreateForm(StyledFormMixin, UserCreationForm):
    role = forms.ChoiceField(label="Роль", choices=Role.choices)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("first_name", "last_name","username",  "email", "role")

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)

        if actor is not None:
            actor_rank = user_rank(actor)
            self.fields["role"].choices = [
                (value, label)
                for value, label in Role.choices
                if role_rank(value) <= actor_rank
            ]

        self.apply_styles()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        if commit:
            user.save()
            StaffProfile.objects.update_or_create(
                user=user, defaults={"role": self.cleaned_data["role"]}
            )
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class ChildForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Child
        fields = (
            "last_name", "first_name", "patronymic", "birth_date", "birth_year", "sex",
            "parent_name", "parent_phone", "second_parent_name", "second_parent_phone",
            "address", "dispensary_region",
            "certificate_note", "group", "status", "trial_from",
            "discount_percent", "note",
        )
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "trial_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birth_date"].input_formats = ["%Y-%m-%d"]
        self.fields["trial_from"].input_formats = ["%Y-%m-%d"]
        self.fields["parent_name"].label = "Родитель 1"
        self.fields["parent_phone"].label = "Телефон родителя 1"
        self.fields["second_parent_name"].label = "Родитель 2"
        self.fields["second_parent_phone"].label = "Телефон родителя 2"
        self.fields["address"].label = "Адрес прописки"
        self.fields["sex"].choices = [
            ("", "— Не указан —"),
            *Child.Sex.choices,
        ]
        self.fields["dispensary_region"].label = "Регион диспансеризации"
        self.fields["dispensary_region"].choices = [
            ("", "— Не указано —"),
            (Child.DispensaryRegion.MOSCOW, "Москва"),
            (Child.DispensaryRegion.MOSCOW_REGION, "Московская область"),
            (Child.DispensaryRegion.OTHER, "Другой регион"),
        ]
        self.fields["dispensary_region"].help_text = (
            "Поле хранит регион, а не конкретное медицинское учреждение."
        )
        self.fields["group"].required = True
        self.fields["group"].empty_label = "— Выберите группу —"
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        birth_date = cleaned.get("birth_date")
        if birth_date:
            cleaned["birth_year"] = birth_date.year
        return cleaned


class ChildRankForm(StyledFormMixin, forms.Form):
    year = forms.IntegerField(
        label="Год",
        min_value=1900,
        max_value=2100,
    )
    rank = forms.CharField(
        label="Спортивный разряд",
        max_length=50,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class CampStayForm(StyledFormMixin, forms.Form):
    kind = forms.ChoiceField(
        label="Тип",
        choices=Camp.Kind.choices,
        initial=Camp.Kind.CAMP,
    )
    camp_name = forms.CharField(
        label="Название",
        max_length=200,
    )
    start_date = forms.DateField(
        label="Дата начала",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    end_date = forms.DateField(
        label="Дата окончания",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "Дата окончания не может быть раньше начала")
        return cleaned


class TariffForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Tariff
        fields = ("name", "price", "sessions_total", "duration_days", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class SubscriptionChildSelect(forms.Select):
    """Добавляет к спортсмену активные группы, где нужен абонемент."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            memberships = list(instance.group_memberships.all())
            active_memberships = [
                item
                for item in memberships
                if item.archived_at is None
            ]
            group_ids = {
                item.group_id
                for item in active_memberships
                if item.requires_subscription
            }
            if (
                instance.group_id
                and not any(
                    item.group_id == instance.group_id
                    for item in active_memberships
                )
            ):
                # Совместимость со старыми детьми без строки membership.
                group_ids.add(instance.group_id)
            option["attrs"]["data-group-ids"] = ",".join(
                str(group_id)
                for group_id in sorted(group_ids)
            )
            if instance.group_id:
                option["attrs"]["data-primary-group-id"] = str(instance.group_id)
        return option


class SubscriptionGroupSelect(forms.Select):
    """Помечает, настроены ли для группы собственные тарифы."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            configured_tariffs = list(instance.subscription_tariffs.all())
            option["attrs"]["data-tariffs-configured"] = (
                "1" if configured_tariffs else "0"
            )
        return option


class SubscriptionTariffSelect(forms.Select):
    """Помечает тариф группами, в которых он разрешён."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-group-ids"] = ",".join(
                str(group.pk)
                for group in instance.groups.all()
            )
        return option


class SubscriptionForm(StyledFormMixin, forms.ModelForm):
    manual_override = forms.BooleanField(label="Изменить вручную (итоговая цена после скидок)", required=False)

    class Meta:
        model = Subscription
        fields = (
            "child", "group", "tariff", "start_date", "end_date", "sessions_total",
            "price", "promo", "promo_percent", "promo_start_date", "promo_end_date",
            "is_active",
        )
        widgets = {
            "child": SubscriptionChildSelect(),
            "group": SubscriptionGroupSelect(),
            "tariff": SubscriptionTariffSelect(),
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "promo_start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "promo_end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%d"]
        self.fields["end_date"].input_formats = ["%Y-%m-%d"]
        self.fields["promo_start_date"].input_formats = ["%Y-%m-%d"]
        self.fields["promo_end_date"].input_formats = ["%Y-%m-%d"]
        current_child_id = self.instance.child_id if self.instance.pk else None
        current_group_id = self.instance.group_id if self.instance.pk else None
        membership_qs = (
            ChildGroupMembership.objects
            .select_related("group")
            .order_by("-is_primary", "joined_at", "pk")
        )
        self.fields["child"].queryset = (
            Child.objects
            .filter(
                models.Q(
                    status__in=(Child.Status.ACTIVE, Child.Status.TRIAL),
                )
                | models.Q(pk=current_child_id)
            )
            .select_related("group")
            .prefetch_related(
                models.Prefetch(
                    "group_memberships",
                    queryset=membership_qs,
                )
            )
            .distinct()
            .order_by("last_name", "first_name", "pk")
        )
        self.fields["group"].queryset = (
            Group.objects
            .filter(
                models.Q(is_active=True)
                | models.Q(pk=current_group_id)
            )
            .prefetch_related("subscription_tariffs")
            .distinct()
            .order_by("name", "pk")
        )
        self.fields["tariff"].queryset = (
            Tariff.objects
            .filter(
                models.Q(is_active=True)
                | models.Q(pk=self.instance.tariff_id)
            )
            .prefetch_related("groups")
            .distinct()
            .order_by("price", "name")
        )
        self.fields["group"].required = True
        self.fields["group"].empty_label = "— Выберите группу —"
        self.fields["promo_percent"].required = False
        self.fields["manual_override"].initial = False

        initial_child = self.initial.get("child")
        if not self.instance.pk and initial_child:
            initial_child_id = getattr(initial_child, "pk", initial_child)
            child = (
                self.fields["child"].queryset
                .filter(pk=initial_child_id)
                .first()
            )
            if child is not None:
                self.initial["group"] = child.group_id

        if self.instance.pk:
            self.fields["child"].disabled = True
            self.fields["group"].disabled = True
            if self.instance.group_id is None and self.instance.child_id:
                self.initial["group"] = self.instance.child.group_id

        self.fields["end_date"].required = False
        self.fields["sessions_total"].required = False
        self.fields["price"].required = False
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        tariff = cleaned.get("tariff")
        percent = cleaned.get("promo_percent") or 0
        cleaned["promo_percent"] = percent
        child = cleaned.get("child")
        group = cleaned.get("group")

        membership = None
        if child and group:
            cached = getattr(
                child,
                "_prefetched_objects_cache",
                {},
            ).get("group_memberships")
            if cached is not None:
                membership = next(
                    (
                        item
                        for item in cached
                        if item.group_id == group.pk
                        and item.archived_at is None
                    ),
                    None,
                )
            else:
                membership = (
                    child.group_memberships
                    .filter(
                        group=group,
                        archived_at__isnull=True,
                    )
                    .first()
                )

            legacy_primary = (
                membership is None
                and child.group_id == group.pk
            )
            if not legacy_primary and (
                membership is None
                or not membership.requires_subscription
            ):
                self.add_error(
                    "group",
                    (
                        f"Группа «{group.name}» не является активной "
                        "абонементной группой спортсмена."
                    ),
                )

        if group and tariff:
            configured_tariff_ids = set(
                group.subscription_tariffs
                .values_list("pk", flat=True)
            )
            legacy_existing_tariff = (
                self.instance.pk
                and self.instance.tariff_id == tariff.pk
                and "tariff" not in self.changed_data
            )
            if (
                configured_tariff_ids
                and tariff.pk not in configured_tariff_ids
                and not legacy_existing_tariff
            ):
                self.add_error(
                    "tariff",
                    (
                        f"Тариф «{tariff.name}» не назначен группе "
                        f"«{group.name}». Настройте тарифы группы."
                    ),
                )

        if not cleaned.get("manual_override") and tariff:
            # Existing snapshot stays unchanged unless its pricing inputs change.
            reprice = not self.instance.pk or any(key in self.changed_data for key in ("tariff", "child", "promo_percent"))
            cleaned["sessions_total"] = tariff.sessions_total if reprice else self.instance.sessions_total
            individual = min(100, child.discount_percent) if child else 0
            self.instance.discount_percent = individual if reprice else self.instance.discount_percent
            cleaned["price"] = (tariff.price * (100 - individual) / 100 * (100 - percent) / 100).quantize(Decimal("0.01")) if reprice else self.instance.price
            if cleaned.get("start_date"):
                cleaned["end_date"] = cleaned["start_date"] + timedelta(days=tariff.duration_days) if reprice or "start_date" in self.changed_data else self.instance.end_date
        for key in ("sessions_total", "price", "end_date"):
            if cleaned.get(key) is None:
                self.add_error(key, "Выберите тариф или укажите значение вручную")
        if cleaned.get("sessions_total") is not None and cleaned["sessions_total"] < 1:
            self.add_error("sessions_total", "Нужно хотя бы одно занятие")
        if cleaned.get("price") is not None and cleaned["price"] < 0:
            self.add_error("price", "Стоимость не может быть отрицательной")
        if self.instance.cancelled_at and cleaned.get("is_active"):
            self.add_error("is_active", "Отменённый абонемент нельзя восстановить: создайте новый")
        if cleaned.get("start_date") and cleaned.get("end_date") and cleaned["end_date"] < cleaned["start_date"]:
            self.add_error("end_date", "Дата окончания не может быть раньше начала")

        promo = (cleaned.get("promo") or "").strip()
        promo_start_date = cleaned.get("promo_start_date")
        promo_end_date = cleaned.get("promo_end_date")
        start_date = cleaned.get("start_date")

        if promo and not promo_start_date and start_date:
            promo_start_date = start_date
            cleaned["promo_start_date"] = promo_start_date

        if promo and not promo_end_date:
            self.add_error(
                "promo_end_date",
                "Для акции укажите дату окончания",
            )
        elif (promo_start_date or promo_end_date) and not promo:
            self.add_error(
                "promo",
                "Укажите название акции",
            )

        if (
            promo_start_date
            and promo_end_date
            and promo_end_date < promo_start_date
        ):
            self.add_error(
                "promo_end_date",
                "Дата окончания акции не может быть раньше даты начала акции",
            )

        return cleaned


class ApparatusForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Apparatus
        fields = ("name",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class LeadGroupSelect(forms.Select):
    """Добавляет группе ID тренера для зависимого выбора в форме заявки."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-trainer-id"] = str(instance.trainer_id)
        return option


class LeadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        fields = ("full_name", "birth_date", "source", "phone", "trial_at", "trainer", "group", "comment")
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "trial_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "group": LeadGroupSelect(),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birth_date"].input_formats = ["%Y-%m-%d"]
        self.fields["birth_date"].help_text = "Возраст рассчитывается автоматически"
        self.fields["trial_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance.pk and self.instance.newcomers.exists():
            for name in ("trial_at", "trainer", "group", "comment"):
                self.initial[name] = getattr(self.instance.current_trial, name)
                self.fields[name].disabled = True
                self.fields[name].help_text = "Пробное изменяется в разделе «Новички»"
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        trainer = cleaned.get("trainer")
        group = cleaned.get("group")
        if group and not trainer:
            self.add_error("group", "Сначала выберите тренера")
        elif group and group.trainer_id != trainer.pk:
            self.add_error("group", "Выберите группу выбранного тренера")
        return cleaned


class NewcomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Newcomer
        fields = (
            "full_name", "birth_date", "age_text", "phone", "source", "trial_at",
            "trainer", "group", "attended", "lesson_cancelled", "comment",
        )
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "trial_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birth_date"].input_formats = ["%Y-%m-%d"]
        self.fields["trial_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.trial_at and "trial_at" in self.changed_data and not (cleaned.get("comment") or "").strip():
            self.add_error("comment", "Укажите причину переноса пробного")
        if cleaned.get("group"):
            cleaned["trainer"] = cleaned["group"].trainer
        if cleaned.get("attended") and cleaned.get("lesson_cancelled"):
            self.add_error("lesson_cancelled", "Нельзя одновременно отметить приход и отмену")
        return cleaned

class TrainerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Trainer
        fields = (
            "full_name",
            "phone",
            "is_active",
            "note",
        )
        widgets = {
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class GroupForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Group
        fields = (
            "name",
            "trainer",
            "capacity",
            "subscription_tariffs",
            "single_session_price",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_tariff_ids = (
            self.instance.subscription_tariffs.values_list("pk", flat=True)
            if self.instance.pk
            else []
        )
        self.fields["subscription_tariffs"].queryset = (
            Tariff.objects
            .filter(
                models.Q(is_active=True)
                | models.Q(pk__in=current_tariff_ids)
            )
            .distinct()
            .order_by("price", "name")
        )
        self.fields["subscription_tariffs"].label = "Абонементные тарифы"
        self.fields["subscription_tariffs"].help_text = (
            "Цена, число занятий и срок берутся из тарифа и не дублируются в группе."
        )
        self.fields["single_session_price"].required = False
        self.fields["single_session_price"].help_text = (
            "Отдельная стоимость только для разового посещения или занятия в долг. "
            "Оставьте пустым, если такие занятия не используются."
        )
        self.apply_styles()

    def clean_single_session_price(self):
        return self.cleaned_data.get("single_session_price") or Decimal("0")


ScheduleSlotFormSet = inlineformset_factory(
    Group,
    ScheduleSlot,
    fields=(
        "weekday",
        "start_time",
        "duration_minutes",
    ),
    extra=1,
    can_delete=True,
    widgets={
        "weekday": forms.Select(attrs={"class": "field"}),
        "start_time": forms.TimeInput(
            attrs={
                "class": "field",
                "type": "time",
            }
        ),
        "duration_minutes": forms.NumberInput(
            attrs={
                "class": "field",
                "min": "15",
                "max": "180",
                "step": "15",
            }
        ),
    },
)


class CampEventForm(StyledFormMixin, forms.ModelForm):
    children = forms.ModelMultipleChoiceField(
        label="Участники", queryset=Child.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        from .models import Camp
        model = Camp
        fields = ("name", "kind", "start_date", "end_date")
        widgets = {key: forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}) for key in ("start_date", "end_date")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].required = self.fields["end_date"].required = True
        if self.instance.pk:
            self.fields["children"].initial = self.instance.campstay_set.values_list("child_id", flat=True)
        self.apply_styles()

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "Окончание не может быть раньше начала")
        return data


class CompetitionDocumentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        from .models import CompetitionDocument
        model = CompetitionDocument
        fields = ("title", "child", "file")

    def __init__(self, *args, competition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["child"].queryset = Child.objects.filter(competition_entries__competition=competition).distinct()
        self.apply_styles()

    def clean_file(self):
        from django.core.validators import FileExtensionValidator
        file = self.cleaned_data["file"]
        FileExtensionValidator(["pdf", "png", "jpg", "jpeg", "docx", "xlsx"])(file)
        if file.size > 20 * 1024 * 1024:
            raise forms.ValidationError("Максимальный размер — 20 МБ")
        return file
