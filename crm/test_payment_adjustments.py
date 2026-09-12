from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditEvent, Child, Payment, Newcomer, Group, Trainer


class PaymentAdjustmentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="refund-boss", password="test")
        self.client.force_login(self.user)
        group = Group.objects.create(name="Группа", trainer=Trainer.objects.create(full_name="Тренер"))
        self.child = Child.objects.create(first_name="Анна", last_name="Возврат", birth_year=2016, group=group)
        self.payment = Payment.objects.create(child=self.child, amount=Decimal("100.50"))
        self.url = reverse("payment_adjustment", args=[self.payment.pk])

    def data(self, amount="40.25", kind="refund"):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return {"amount": amount, "kind": kind, "reason": "Возврат по заявлению", "date": timezone.localdate().isoformat(), "token": response.context["form"].initial["token"]}

    def test_partial_refund_is_linked_audited_and_idempotent(self):
        data = self.data()
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        entry = self.payment.adjustments.get()
        self.assertEqual(entry.amount, Decimal("-40.25"))
        self.assertEqual(entry.created_by, self.user)
        self.assertTrue(AuditEvent.objects.filter(action="payment.refund", object_id=str(entry.pk)).exists())
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(self.payment.adjustments.count(), 1)
        self.assertEqual(Payment.objects.aggregate(net=Sum("amount"))["net"], Decimal("60.25"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount, Decimal("100.50"))
        data["amount"] = "20"
        response = self.client.post(self.url, data)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertEqual(self.payment.adjustments.count(), 1)

    def test_cannot_exceed_remaining_even_with_a_new_token(self):
        self.client.post(self.url, self.data("60"))
        response = self.client.post(self.url, self.data("41"))
        self.assertIn("amount", response.context["form"].errors)
        self.assertEqual(self.payment.adjustments.count(), 1)

    def test_full_correction_updates_newcomer_and_history(self):
        newcomer = Newcomer.objects.create(full_name="Анна Возврат", child=self.child)
        self.client.post(self.url, self.data("100.50", "correction"))
        newcomer.refresh_from_db()
        self.assertFalse(newcomer.has_paid)
        self.assertFalse(newcomer.paid)
        history = self.client.get(reverse("payment_history"), {"month": timezone.localdate().strftime("%Y-%m")})
        self.assertEqual(history.context["total"], 0)
        self.assertContains(history, "Сторно ошибочной оплаты")
        self.assertContains(history, "Возврат по заявлению")

    def test_bad_token_date_reason_and_permissions_do_not_write(self):
        data = self.data()
        for changes in ({"token": "forged"}, {"date": "2100-01-01"}, {"reason": ""}, {"amount": "-1"}):
            response = self.client.post(self.url, {**data, **changes})
            self.assertTrue(response.context["form"].errors)
        other = get_user_model().objects.create_user(username="refund-manager")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, data).status_code, 403)
        self.assertFalse(self.payment.adjustments.exists())

    def test_cannot_reverse_a_refund(self):
        self.client.post(self.url, self.data())
        self.assertEqual(self.client.get(reverse("payment_adjustment", args=[self.payment.adjustments.get().pk])).status_code, 404)
