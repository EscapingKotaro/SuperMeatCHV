from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from .models import (
    Apparatus,
    Child,
    Competition,
    CompetitionEntry,
    Expense,
    Lead,
    ManagerTask,
    Newcomer,
    Reminder,
    RevenueTarget,
    Role,
    StaffProfile,
    Subscription,
    Tariff,
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


class ManagerTaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ManagerTask
        fields = ("title", "description", "assignee", "due_date")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["assignee"].queryset = user_model.objects.filter(
            is_active=True, is_staff=True
        ).exclude(profile__role=Role.BOSS).order_by("first_name", "last_name", "username")
        self.fields["assignee"].required = False
        self.fields["assignee"].empty_label = "Всем администраторам"
        self.fields["due_date"].input_formats = ["%Y-%m-%d"]
        self.apply_styles()


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
        fields = ("child", "category", "rank")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class StaffCreateForm(StyledFormMixin, UserCreationForm):
    role = forms.ChoiceField(label="Роль", choices=Role.choices)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            "last_name", "first_name", "patronymic", "birth_date", "birth_year",
            "address", "parent_name", "parent_phone", "certificate",
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
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        birth_date = cleaned.get("birth_date")
        if birth_date:
            cleaned["birth_year"] = birth_date.year
        return cleaned


class TariffForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Tariff
        fields = ("name", "price", "sessions_total", "duration_days", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class SubscriptionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ("child", "tariff", "start_date", "end_date", "sessions_total", "price", "promo", "is_active")
        widgets = {
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%d"]
        self.fields["end_date"].input_formats = ["%Y-%m-%d"]
        self.fields["tariff"].queryset = Tariff.objects.filter(is_active=True)
        self.fields["end_date"].required = False
        self.fields["sessions_total"].required = False
        self.fields["price"].required = False
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        tariff = cleaned.get("tariff")
        if tariff:
            cleaned["sessions_total"] = tariff.sessions_total
            cleaned["price"] = tariff.price
            if cleaned.get("start_date") and not cleaned.get("end_date"):
                cleaned["end_date"] = cleaned["start_date"] + timedelta(days=tariff.duration_days)
        if cleaned.get("start_date") and cleaned.get("end_date") and cleaned["end_date"] < cleaned["start_date"]:
            self.add_error("end_date", "Дата окончания не может быть раньше начала")
        return cleaned


class ApparatusForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Apparatus
        fields = ("name", "order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class LeadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        fields = ("full_name", "birth_date", "age_text", "source", "phone", "trial_at", "trainer", "group", "status", "comment")
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


class ReminderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ("title", "description", "remind_at", "assignee", "visible_to_all")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "remind_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["remind_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.apply_styles()


class NewcomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Newcomer
        fields = (
            "full_name", "birth_date", "age_text", "phone", "source", "trial_at",
            "trainer", "group", "attended", "paid", "lesson_cancelled", "comment",
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
