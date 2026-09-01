from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Apparatus,
    ApparatusScore,
    Attendance,
    Child,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    ManagerTask,
    Newcomer,
    Reminder,
    Role,
    StaffProfile,
    Subscription,
    Tariff,
    Trainer,
)


class CrmWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.boss = user_model.objects.create_user("boss", password="TestPass123!", is_staff=True)
        self.senior = user_model.objects.create_user("senior", password="TestPass123!", is_staff=True)
        self.admin = user_model.objects.create_user("admin", password="TestPass123!", is_staff=True)
        StaffProfile.objects.create(user=self.boss, role=Role.BOSS)
        StaffProfile.objects.create(user=self.senior, role=Role.SENIOR)
        StaffProfile.objects.create(user=self.admin, role=Role.MANAGER)
        self.trainer = Trainer.objects.create(full_name="Тестовый тренер")
        self.group = Group.objects.create(name="Тестовая группа", trainer=self.trainer)
        self.child = Child.objects.create(last_name="Иванова", first_name="Анна", birth_year=2015, group=self.group)

    def test_private_pages_require_login(self):
        response = self.client.get(reverse("expenses"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('expenses')}")

    def test_role_access_to_boss_page(self):
        self.client.login(username="admin", password="TestPass123!")
        self.assertEqual(self.client.get(reverse("boss")).status_code, 403)
        self.client.logout()
        self.client.login(username="boss", password="TestPass123!")
        self.assertEqual(self.client.get(reverse("boss")).status_code, 200)

    def test_admin_can_create_expense(self):
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(reverse("expenses"), {
            "title": "Вода", "category": Expense.Category.HOUSEHOLD,
            "amount": "1250.50", "date": timezone.localdate().isoformat(),
        })
        self.assertRedirects(response, reverse("expenses"))
        self.assertTrue(Expense.objects.filter(title="Вода", created_by=self.admin).exists())

    def test_boss_assigns_task_and_admin_completes_it(self):
        self.client.login(username="boss", password="TestPass123!")
        response = self.client.post(reverse("boss"), {
            "action": "create_task", "task-title": "Позвонить родителю",
            "task-description": "Уточнить оплату", "task-assignee": self.admin.pk,
            "task-due_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
        })
        self.assertRedirects(response, reverse("boss"))
        task = ManagerTask.objects.get(title="Позвонить родителю")
        self.client.logout()
        self.client.login(username="admin", password="TestPass123!")
        self.client.post(reverse("notifications"), {"task_id": task.pk})
        task.refresh_from_db()
        self.assertTrue(task.is_done)
        self.assertIsNotNone(task.done_at)

    def test_attendance_mark_is_saved(self):
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(
            reverse("attendance"),
            {"action": "mark", "child_id": self.child.pk, "date": timezone.localdate().isoformat(), "status": Attendance.Status.PRESENT},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Attendance.objects.filter(child=self.child, status=Attendance.Status.PRESENT).exists())

    def test_competition_scores_places_and_export(self):
        competition = Competition.objects.create(name="Кубок", date=timezone.localdate())
        apparatus = Apparatus.objects.create(competition=competition, name="Прыжок")
        other = Child.objects.create(last_name="Петрова", first_name="Мария", birth_year=2015, group=self.group)
        first = CompetitionEntry.objects.create(child=self.child, competition=competition, category="2015")
        second = CompetitionEntry.objects.create(child=other, competition=competition, category="2015")
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(f"{reverse('competitions')}?competition={competition.pk}", {
            "action": "save_scores", f"score_{first.pk}_{apparatus.pk}": "9.5", f"score_{second.pk}_{apparatus.pk}": "8.2",
        })
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.place, 1)
        self.assertEqual(second.place, 2)
        self.assertEqual(ApparatusScore.objects.get(entry=first).points, Decimal("9.500"))
        export = self.client.get(reverse("competition_export", args=[competition.pk]))
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export["Content-Type"])

    def test_senior_can_create_staff_account(self):
        self.client.login(username="senior", password="TestPass123!")
        response = self.client.post(reverse("users"), {
            "action": "create", "username": "new-admin", "first_name": "Новый",
            "last_name": "Администратор", "email": "new@example.test", "role": Role.MANAGER,
            "password1": "StrongPass123!", "password2": "StrongPass123!",
        })
        self.assertRedirects(response, reverse("users"))
        self.assertEqual(get_user_model().objects.get(username="new-admin").profile.role, Role.MANAGER)

    def test_senior_cannot_create_boss_account(self):
        self.client.login(username="senior", password="TestPass123!")
        response = self.client.post(reverse("users"), {
            "action": "create", "username": "other-boss", "role": Role.BOSS,
            "password1": "StrongPass123!", "password2": "StrongPass123!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="other-boss").exists())

    def test_child_card_can_convert_trial_to_active(self):
        self.child.status = Child.Status.TRIAL
        self.child.trial_from = timezone.localdate()
        self.child.save()
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(reverse("child_edit", args=[self.child.pk]), {
            "action": "save", "next": reverse("attendance"),
            f"child-{self.child.pk}-last_name": "Иванова",
            f"child-{self.child.pk}-first_name": "Анна",
            f"child-{self.child.pk}-patronymic": "",
            f"child-{self.child.pk}-birth_year": "2015",
            f"child-{self.child.pk}-status": Child.Status.ACTIVE,
            f"child-{self.child.pk}-group": self.group.pk,
            f"child-{self.child.pk}-discount_percent": "0",
        })
        self.assertRedirects(response, reverse("attendance"))
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.ACTIVE)
        self.assertIsNone(self.child.trial_from)

    def test_tariff_and_subscription_can_be_assigned(self):
        self.client.login(username="admin", password="TestPass123!")
        self.client.post(reverse("payments"), {
            "action": "save_tariff", "tariff-name": "Месяц",
            "tariff-price": "6000", "tariff-sessions_total": "8",
            "tariff-duration_days": "30", "tariff-is_active": "on",
        })
        tariff = Tariff.objects.get(name="Месяц")
        start = timezone.localdate()
        self.client.post(reverse("payments"), {
            "action": "save_subscription", "subscription-child": self.child.pk,
            "subscription-tariff": tariff.pk, "subscription-start_date": start.isoformat(),
            "subscription-promo": "", "subscription-is_active": "on",
        })
        subscription = Subscription.objects.get(child=self.child)
        self.assertEqual(subscription.price, Decimal("6000"))
        self.assertEqual(subscription.end_date, start + timedelta(days=30))

    def test_application_creates_prefilled_newcomer(self):
        lead = Lead.objects.create(full_name="Петрова Ева", phone="123", source="VK")
        self.client.login(username="admin", password="TestPass123!")
        self.client.post(reverse("applications"), {"action": "create_newcomer", "lead_id": lead.pk})
        newcomer = Newcomer.objects.get(lead=lead)
        self.assertEqual(newcomer.phone, "123")
        self.assertEqual(newcomer.full_name, "Петрова Ева")

    def test_calendar_reminder_and_backup_pages(self):
        self.client.login(username="admin", password="TestPass123!")
        remind_at = timezone.now() + timedelta(hours=2)
        response = self.client.post(reverse("calendar"), {
            "action": "save", "title": "Перезвонить", "description": "",
            "remind_at": remind_at.strftime("%Y-%m-%dT%H:%M"),
            "assignee": self.admin.pk, "visible_to_all": "on",
        })
        self.assertRedirects(response, reverse("calendar"))
        self.assertTrue(Reminder.objects.filter(title="Перезвонить").exists())
        self.assertEqual(self.client.get(reverse("backup_export")).status_code, 403)
        self.client.logout(); self.client.login(username="senior", password="TestPass123!")
        self.assertEqual(self.client.get(reverse("backup_export")).status_code, 200)

    def test_all_primary_pages_render(self):
        self.client.login(username="boss", password="TestPass123!")
        for name in ("attendance", "applications", "newcomers", "calendar", "payments", "expenses", "competitions", "notifications", "search", "statistics", "boss", "users", "profile"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
