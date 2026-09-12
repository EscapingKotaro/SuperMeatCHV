from datetime import timedelta

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, Child, Group, Newcomer, Payment, Subscription, Trainer, TrialCredit
from .trial_credit import credit_paid_trial


class TrialCreditTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.group = Group.objects.create(name="Рабочая", trainer=Trainer.objects.create(full_name="Тренер"))
        self.trial_group = Group.objects.create(name="Пробная", trainer=self.group.trainer)
        self.child = Child.objects.create(first_name="Анна", last_name="Пробная", birth_year=2016, group=self.group)
        self.sub = Subscription.objects.create(child=self.child, group=self.group, start_date=self.today,
            end_date=self.today + timedelta(days=30), sessions_total=8, price=100)
        self.newcomer = Newcomer.objects.create(child=self.child, group=self.trial_group, full_name="Анна Пробная",
            attended=True, trial_at=timezone.now()-timedelta(days=2))

    def test_trial_before_start_in_another_group_counts_once_without_new_mark(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        credit = credit_paid_trial(self.sub)
        self.assertIsNotNone(credit)
        self.assertEqual(self.sub.sessions_used(), 1)
        self.assertEqual(self.child.sessions_left(), 7)
        self.assertFalse(Attendance.objects.filter(child=self.child).exists())
        self.assertIsNone(credit_paid_trial(self.sub))
        self.assertEqual(TrialCredit.objects.count(), 1)
        self.assertEqual(self.sub.sessions_used(), 1)

    def test_trial_inside_normal_attendance_period_is_not_counted_twice(self):
        self.sub.start_date = self.today-timedelta(days=3)
        self.sub.save()
        Attendance.objects.create(child=self.child, group_snapshot=self.group,
            date=timezone.localtime(self.newcomer.trial_at).date(), status="present")
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        credit_paid_trial(self.sub)
        self.assertEqual(self.sub.sessions_used(), 1)

    def test_partial_payment_remembers_trial_until_final_payment(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=40)
        self.assertIsNone(credit_paid_trial(self.sub))
        self.assertEqual(self.sub.sessions_used(), 0)
        self.assertIsNone(TrialCredit.objects.get().subscription_id)
        Payment.objects.create(child=self.child, subscription=self.sub, amount=60)
        self.assertIsNotNone(credit_paid_trial(self.sub))
        self.assertEqual(self.sub.sessions_used(), 1)

    def test_absent_or_future_trial_is_not_credited(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        self.newcomer.attended = False
        self.newcomer.save()
        self.assertIsNone(credit_paid_trial(self.sub))
        self.newcomer.attended = True
        self.newcomer.trial_at = timezone.now()+timedelta(days=2)
        self.newcomer.save()
        self.assertIsNone(credit_paid_trial(self.sub))

    def test_credit_is_not_reused_on_next_subscription(self):
        Payment.objects.create(child=self.child, subscription=self.sub, amount=100)
        credit_paid_trial(self.sub)
        another = Subscription.objects.create(child=self.child, start_date=self.today+timedelta(days=31),
            end_date=self.today+timedelta(days=60), price=100)
        Payment.objects.create(child=self.child, subscription=another, amount=100)
        self.assertIsNone(credit_paid_trial(another))
        self.assertEqual(TrialCredit.objects.get().subscription_id, self.sub.pk)

    def test_real_payment_form_applies_credit(self):
        from .payment_submission import issue_token
        user = get_user_model().objects.create_user(username="trial-payment", is_staff=True)
        self.client.force_login(user)
        response = self.client.post(reverse("payments"), {"action": "payment", "child_id": self.child.pk,
            "amount": "100", "date": self.today.isoformat(), "subscription_id": self.sub.pk,
            "submission_token": issue_token(user.pk)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TrialCredit.objects.get().subscription_id, self.sub.pk)
        self.assertEqual(self.child.sessions_left(), 7)
