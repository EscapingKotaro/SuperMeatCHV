from django import forms
from .models import Child, Subscription, Group

class ChildForm(forms.ModelForm):
    class Meta:
        model = Child
        fields = [
            'last_name', 'first_name', 'patronymic',
            'address', 'parent_name', 'parent_phone', 'certificate',
            'certificate_note', 'group', 'status', 'trial_from',
            'discount_percent', 'note'
        ]
        widgets = {
            'last_name': forms.TextInput(attrs={'class': 'field'}),
            'first_name': forms.TextInput(attrs={'class': 'field'}),
            'patronymic': forms.TextInput(attrs={'class': 'field'}),
            'address': forms.TextInput(attrs={'class': 'field'}),
            'parent_name': forms.TextInput(attrs={'class': 'field'}),
            'parent_phone': forms.TextInput(attrs={'class': 'field', 'placeholder': '+7 (___) ___-__-__'}),
            'certificate_note': forms.TextInput(attrs={'class': 'field'}),
            'group': forms.Select(attrs={'class': 'field'}),
            'status': forms.Select(attrs={'class': 'field'}),
            'trial_from': forms.DateInput(attrs={'class': 'field', 'type': 'date'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'field', 'min': '0', 'max': '100'}),
            'note': forms.Textarea(attrs={'class': 'field', 'rows': '4'}),
        }

class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['start_date', 'end_date', 'sessions_total', 'price', 'promo']
        widgets = {
            'start_date': forms.DateInput(attrs={'class': 'field', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'field', 'type': 'date'}),
            'sessions_total': forms.NumberInput(attrs={'class': 'field', 'min': '1'}),
            'price': forms.NumberInput(attrs={'class': 'field', 'step': '0.01'}),
            'promo': forms.TextInput(attrs={'class': 'field'}),
        }


from django import forms
from django.forms import inlineformset_factory
from .models import Trainer, Group, ScheduleSlot, Child, Subscription

# --- Тренер ---
class TrainerForm(forms.ModelForm):
    class Meta:
        model = Trainer
        fields = ['full_name', 'phone', 'is_active', 'note']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'field'}),
            'phone': forms.TextInput(attrs={'class': 'field', 'placeholder': '+7 (___) ___-__-__'}),
            'note': forms.Textarea(attrs={'class': 'field', 'rows': '3'}),
        }

# --- Группа ---
class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'trainer', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'field'}),
            'trainer': forms.Select(attrs={'class': 'field'}),
        }

# --- Расписание (inline formset) ---
ScheduleSlotFormSet = inlineformset_factory(
    Group,
    ScheduleSlot,
    fields=['weekday', 'start_time', 'duration_minutes'],
    extra=1,  # Одна пустая форма для добавления
    can_delete=True,
    widgets={
        'weekday': forms.Select(attrs={'class': 'field'}),
        'start_time': forms.TimeInput(attrs={'class': 'field', 'type': 'time'}),
        'duration_minutes': forms.NumberInput(attrs={'class': 'field', 'min': '15', 'max': '180', 'step': '15'}),
    }
)
