from django import forms
from .models import Child, Subscription, Group

class ChildForm(forms.ModelForm):
    class Meta:
        model = Child
        fields = [
            'last_name', 'first_name', 'patronymic', 'birth_year',
            'address', 'parent_name', 'parent_phone', 'certificate',
            'certificate_note', 'group', 'status', 'trial_from',
            'discount_percent', 'note'
        ]
        widgets = {
            'last_name': forms.TextInput(attrs={'class': 'field'}),
            'first_name': forms.TextInput(attrs={'class': 'field'}),
            'patronymic': forms.TextInput(attrs={'class': 'field'}),
            'birth_year': forms.NumberInput(attrs={'class': 'field', 'min': '1990', 'max': '2024'}),
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
