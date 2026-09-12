from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Attendance, Payment, Subscription, TrialCredit
from .test_trial_credit import TrialCreditTests


class TrialManagementTests(TestCase):
    def setUp(self):
        TrialCreditTests.setUp(self)
        self.user = get_user_model().objects.create_superuser(username="review-boss", password="test")
        self.client.force_login(self.user)
        self.url = reverse("trial_management", args=[self.child.pk])

    def review_data(self, **changes):
        page = self.client.get(self.url)
        data = {"action": "review", "subscription": self.sub.pk, "date": self.today.isoformat(),
            "group": self.trial_group.pk, "reason": "Проверено по заявлению", "version": page.context["review"].initial["version"]}
        return {**data, **changes}

    def test_allocate_prepaid_money_and_refunds_without_new_payment(self):
        payment = Payment.objects.create(child=self.child, amount=120)
        refund = Payment.objects.create(child=self.child, original_payment=payment, operation_kind="refund", amount=-20)
        response = self.client.post(self.url, {"action": "allocate", "payment": payment.pk, "subscription": self.sub.pk})
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db(); refund.refresh_from_db()
        self.assertEqual(payment.subscription_id, self.sub.pk)
        self.assertEqual(refund.subscription_id, self.sub.pk)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(TrialCredit.objects.get().subscription_id, self.sub.pk)
        repeated = self.client.post(self.url, {"action": "allocate", "payment": payment.pk, "subscription": self.sub.pk})
        self.assertTrue(repeated.context["allocation"].errors)

    def test_confirmation_after_payment_credits_automatically(self):
        self.newcomer.attended = False
        self.newcomer.save()
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        self.newcomer.attended = True
        self.newcomer.save()
        self.assertEqual(TrialCredit.objects.get().subscription_id, self.sub.pk)

    def test_multiple_paid_subscriptions_require_explicit_review(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        other = Subscription.objects.create(child=self.child, start_date=self.sub.start_date, end_date=self.sub.end_date, price=100)
        Payment.objects.create(child=self.child, subscription=other, amount=100)
        self.newcomer.save()
        self.assertFalse(TrialCredit.objects.exists())
        self.assertEqual(self.client.post(self.url, self.review_data()).status_code, 302)
        self.assertEqual(TrialCredit.objects.get().subscription_id, self.sub.pk)

    def test_remove_suppresses_automatic_recredit_and_stale_form_is_rejected(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        old = self.review_data()
        self.client.post(self.url, old)
        self.assertTrue(self.client.post(self.url, old).context["review"].errors)
        self.client.post(self.url, self.review_data(remove="on"))
        self.newcomer.save()
        credit = TrialCredit.objects.get()
        self.assertTrue(credit.is_void)
        self.assertIsNone(credit.subscription_id)

    def test_transfer_updates_single_credit(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        self.client.post(self.url, self.review_data())
        other = Subscription.objects.create(child=self.child, start_date=self.sub.start_date, end_date=self.sub.end_date, price=100)
        Payment.objects.create(child=self.child, subscription=other, amount=100)
        self.client.post(self.url, self.review_data(subscription=other.pk))
        self.assertEqual(TrialCredit.objects.count(), 1)
        self.assertEqual(TrialCredit.objects.get().subscription_id, other.pk)

    def test_get_is_read_only_and_financial_conflict_blocks_change(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        self.client.get(self.url)
        self.assertFalse(TrialCredit.objects.exists())
        Attendance.objects.create(child=self.child, date=self.today, status="absent", charge_amount=50)
        response = self.client.post(self.url, self.review_data())
        self.assertTrue(response.context["review"].errors)
        self.assertFalse(TrialCredit.objects.exists())

    def test_manager_cannot_modify_review(self):
        manager = get_user_model().objects.create_user(username="review-manager")
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"action": "allocate"}).status_code, 403)
