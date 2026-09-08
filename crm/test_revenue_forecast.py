from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, Child, Group, Payment, ScheduleSlot, Subscription, Trainer


class RevenueForecastRegressionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            "forecast-admin",
            password="TestPass123!",
            is_staff=True,
        )
        self.trainer = Trainer.objects.create(full_name="Тестовый тренер прогноза")
        self.group = Group.objects.create(
            name="Тестовая группа прогноза",
            trainer=self.trainer,
        )
        self.child = Child.objects.create(
            last_name="Иванова",
            first_name="Анна",
            birth_year=2015,
            group=self.group,
            status=Child.Status.ACTIVE,
        )

    def test_sessions_left_ignores_attendance_before_current_subscription(self):
        today = timezone.localdate()
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )

        Attendance.objects.create(
            child=self.child,
            date=subscription.start_date - timedelta(days=1),
            status=Attendance.Status.PRESENT,
        )
        for offset in (4, 3, 2, 1):
            Attendance.objects.create(
                child=self.child,
                date=today - timedelta(days=offset),
                status=Attendance.Status.PRESENT,
            )

        self.assertEqual(self.child.sessions_left(), 4)

    def test_projected_end_does_not_count_marked_today_twice(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=30),
            sessions_total=2,
            price=Decimal("6000"),
            is_active=True,
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
        )

        self.assertEqual(self.child.sessions_left(), 1)
        self.assertEqual(
            self.child.projected_end_date(),
            today + timedelta(days=7),
        )

    def test_four_sessions_do_not_enter_four_day_forecast(self):
        today = timezone.localdate()
        for offset in (0, 2, 4):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=(today.weekday() + offset) % 7,
                start_time=time(18, 0),
            )

        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=4,
            price=Decimal("6000"),
            is_active=True,
        )

        self.client.login(username="forecast-admin", password="TestPass123!")
        response = self.client.get(reverse("revenue_forecast"))

        self.assertEqual(response.status_code, 200)
        names = {
            item["name"]
            for day in response.context["days"]
            for bucket in ("urgent", "one_left", "forecast")
            for item in day[bucket]
        }
        self.assertNotIn("Иванова Анна", names)

    def test_forecast_uses_net_amount_after_prepayment(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=1,
            price=Decimal("6000"),
            is_active=True,
        )
        Payment.objects.create(
            child=self.child,
            subscription=subscription,
            amount=Decimal("9000"),
            date=today,
            created_by=self.user,
        )

        self.client.login(username="forecast-admin", password="TestPass123!")
        response = self.client.get(reverse("revenue_forecast"))

        self.assertEqual(response.status_code, 200)
        today_row = response.context["days"][0]
        item = next(
            item
            for bucket in ("urgent", "one_left", "forecast")
            for item in today_row[bucket]
            if item["name"] == "Иванова Анна"
        )
        self.assertEqual(item["amount"], Decimal("3000"))
        self.assertEqual(today_row["total"], Decimal("3000"))
