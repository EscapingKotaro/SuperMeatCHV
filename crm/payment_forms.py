from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import Child, Group, Subscription


class PaymentEntryForm(forms.Form):
    child_id = forms.ModelChoiceField(queryset=Child.objects.all(), label="Спортсмен")
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=10, decimal_places=2, label="Сумма")
    date = forms.DateField(label="Дата")
    subscription_id = forms.ModelChoiceField(queryset=Subscription.objects.none(), required=False, label="Абонемент")
    working_group_id = forms.ModelChoiceField(queryset=Group.objects.filter(is_active=True), required=False, label="Рабочая группа")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].initial = timezone.localdate().isoformat()
        raw_child = self.data.get("child_id") if self.is_bound else self.initial.get("child_id")
        try:
            child_id = int(raw_child)
        except (ValueError, TypeError):
            child_id = None
        self.fields["subscription_id"].queryset = Subscription.objects.filter(child_id=child_id, cancelled_at__isnull=True)
        self.fields["subscription_id"].error_messages["invalid_choice"] = "Абонемент отменён или не принадлежит выбранному спортсмену. Выберите другой."
        self.fields["working_group_id"].error_messages["invalid_choice"] = "Рабочая группа недоступна. Выберите действующую группу."

    def clean(self):
        data = super().clean()
        child = data.get("child_id")
        if child and child.status == Child.Status.TRIAL and not data.get("working_group_id") and "working_group_id" not in self.errors:
            self.add_error("working_group_id", "Для пробника выберите рабочую группу после оплаты")
        return data
