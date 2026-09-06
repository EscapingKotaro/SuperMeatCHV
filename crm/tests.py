from datetime import time, timedelta
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
    Notification,
    Newcomer,
    Role,
    StaffProfile,
    Subscription,
    Tariff,
    ScheduleSlot,
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
        
    def test_opening_notifications_marks_them_read(self):
        notification = Notification.objects.create(
            recipient=self.admin,
            actor=self.boss,
            kind=Notification.Kind.TASK_CREATED,
            message="Новая задача",
        )

        self.client.login(username="admin", password="TestPass123!")
        self.client.get(reverse("notifications"))

        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_boss_assigns_task_and_admin_completes_it(self):
        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("boss"),
            {
                "action": "create_task",
                "task-title": "Позвонить родителю",
                "task-description": "Уточнить оплату",
                "task-assignee": self.admin.pk,
                "task-due_date": (
                    timezone.localdate()
                    + timedelta(days=1)
                ).isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("boss"),
        )

        task = ManagerTask.objects.get(
            title="Позвонить родителю"
        )
        
        self.assertTrue(Notification.objects.filter(
            recipient=self.admin,
            task=task,
            kind=Notification.Kind.TASK_CREATED,
            read_at__isnull=True,
        ).exists())

        self.assertEqual(
            task.created_by,
            self.boss,
        )

        self.assertEqual(
            task.assignee,
            self.admin,
        )

        self.client.logout()

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("notifications"),
            {
                "task_id": task.pk,
                "completion_comment": (
                    "Позвонил, оплату подтвердили"
                ),
            },
        )
        
        self.assertTrue(Notification.objects.filter(
            recipient=self.boss,
            task=task,
            kind=Notification.Kind.TASK_COMPLETED,
            read_at__isnull=True,
        ).exists())

        self.assertRedirects(
            response,
            reverse("notifications"),
        )

        task.refresh_from_db()

        self.assertTrue(
            task.is_done
        )

        self.assertIsNotNone(
            task.done_at
        )

        self.assertEqual(
            task.completed_by,
            self.admin,
        )

        self.assertEqual(
            task.completion_comment,
            "Позвонил, оплату подтвердили",
        )

    def test_attendance_mark_is_saved(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": timezone.localdate().isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.json()["status"],
            "ok",
        )

        self.assertTrue(
            Attendance.objects.filter(
                child=self.child,
                date=timezone.localdate(),
                status=Attendance.Status.PRESENT,
            ).exists()
        )
        
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

        self.child.save(
            update_fields=[
                "status",
                "trial_from",
            ]
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse(
                "child_edit",
                args=[self.child.pk],
            ),
            {
                "next": reverse("attendance"),
                "last_name": "Иванова",
                "first_name": "Анна",
                "patronymic": "",
                "birth_year": "2015",
                "birth_date": "",
                "address": "",
                "parent_name": "",
                "parent_phone": "",
                "certificate_note": "",
                "group": self.group.pk,
                "status": Child.Status.ACTIVE,
                "trial_from": "",
                "discount_percent": "0",
                "note": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("attendance"),
        )

        self.child.refresh_from_db()

        self.assertEqual(
            self.child.status,
            Child.Status.ACTIVE,
        )

        self.assertIsNone(
            self.child.trial_from,
        )

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

    def test_calendar_creates_manager_task(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        start_at = (
            timezone.now()
            + timedelta(days=1)
        ).replace(
            second=0,
            microsecond=0,
        )

        end_at = (
            start_at
            + timedelta(hours=1)
        )

        response = self.client.post(
            reverse("calendar"),
            {
                "action": "save",
                "title": "Позвонить поставщику",
                "description": "Уточнить доставку",
                "assignee": self.admin.pk,
                "scheduled_at": start_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "scheduled_end_at": end_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "due_date": start_at.date().isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("calendar"),
        )

        task = ManagerTask.objects.get(
            title="Позвонить поставщику"
        )

        self.assertEqual(
            task.created_by,
            self.admin,
        )

        self.assertEqual(
            task.assignee,
            self.admin,
        )

        self.assertIsNotNone(
            task.scheduled_at
        )

        self.assertIsNotNone(
            task.scheduled_end_at
        )

        self.assertGreater(
            task.scheduled_end_at,
            task.scheduled_at,
        )


    def test_calendar_rejects_invalid_task_time_range(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        start_at = (
            timezone.now()
            + timedelta(days=1)
        ).replace(
            second=0,
            microsecond=0,
        )

        end_at = (
            start_at
            - timedelta(hours=1)
        )

        response = self.client.post(
            reverse("calendar"),
            {
                "action": "save",
                "title": "Неверный интервал",
                "description": "",
                "assignee": self.admin.pk,
                "scheduled_at": start_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "scheduled_end_at": end_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "due_date": start_at.date().isoformat(),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            ManagerTask.objects.filter(
                title="Неверный интервал"
            ).exists()
        )


    def test_task_author_can_delete_task(self):
        task = ManagerTask.objects.create(
            title="Удалить меня",
            description="",
            assignee=self.admin,
            created_by=self.admin,
            due_date=timezone.localdate(),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("calendar"),
            {
                "action": "delete",
                "task_id": task.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("calendar"),
        )

        self.assertFalse(
            ManagerTask.objects.filter(
                pk=task.pk
            ).exists()
        )


    def test_other_manager_cannot_delete_foreign_task(self):
        task = ManagerTask.objects.create(
            title="Чужая задача",
            description="",
            assignee=self.admin,
            created_by=self.admin,
            due_date=timezone.localdate(),
        )

        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("calendar"),
            {
                "action": "delete",
                "task_id": task.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            ManagerTask.objects.filter(
                pk=task.pk
            ).exists()
        )


    def test_other_manager_cannot_complete_foreign_task(self):
        task = ManagerTask.objects.create(
            title="Задача администратора",
            assignee=self.admin,
            created_by=self.boss,
            due_date=timezone.localdate(),
        )

        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("notifications"),
            {
                "task_id": task.pk,
                "completion_comment": "Попытка",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        task.refresh_from_db()

        self.assertFalse(
            task.is_done
        )

        self.assertIsNone(
            task.completed_by
        )


    def test_common_task_can_be_completed_by_any_manager(self):
        task = ManagerTask.objects.create(
            title="Общая задача",
            assignee=None,
            created_by=self.boss,
            due_date=timezone.localdate(),
        )

        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("notifications"),
            {
                "task_id": task.pk,
                "completion_comment": "Готово",
            },
        )

        self.assertRedirects(
            response,
            reverse("notifications"),
        )

        task.refresh_from_db()

        self.assertTrue(
            task.is_done
        )

        self.assertEqual(
            task.completed_by,
            self.senior,
        )

        self.assertEqual(
            task.completion_comment,
            "Готово",
        )


    def test_completed_task_can_be_returned_to_work(self):
        task = ManagerTask.objects.create(
            title="Вернуть в работу",
            assignee=self.admin,
            created_by=self.boss,
            is_done=True,
            done_at=timezone.now(),
            completed_by=self.admin,
            completion_comment="Первый результат",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("notifications"),
            {
                "task_id": task.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("notifications"),
        )

        task.refresh_from_db()

        self.assertFalse(
            task.is_done
        )

        self.assertIsNone(
            task.done_at
        )

        self.assertIsNone(
            task.completed_by
        )

        self.assertEqual(
            task.completion_comment,
            "",
        )


    def test_backup_permissions(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        self.assertEqual(
            self.client.get(
                reverse("backup_export")
            ).status_code,
            403,
        )

        self.client.logout()

        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        self.assertEqual(
            self.client.get(
                reverse("backup_export")
            ).status_code,
            200,
        )

    def test_all_primary_pages_render(self):
        self.client.login(username="boss", password="TestPass123!")
        for name in ("attendance", "applications", "newcomers", "calendar", "payments", "expenses", "competitions", "notifications", "search", "statistics", "boss", "users", "profile"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_attendance_renders_schedule_window(self):
        today = timezone.localdate()

        for weekday in range(7):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )

        end_date = today + timedelta(days=5)
        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
        )

        self.client.login(username="admin", password="TestPass123!")

        response = self.client.get(reverse("attendance"), {
            "group_id": self.group.pk,
            "ref_date": today.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("week_data", response.context)
        self.assertGreaterEqual(len(response.context["week_data"]), 6)
        self.assertLessEqual(len(response.context["week_data"]), 10)

        child_data = next(
            item for item in response.context["children_data"]
            if item["child"].pk == self.child.pk
        )

        self.assertEqual(child_data["subscription_end"], end_date)

    def test_login_remember_me_sets_two_week_session(self):
        self.client.logout()
        response = self.client.post(reverse("login"), {
            "username": "admin", "password": "TestPass123!", "remember_me": "on",
        })
        self.assertRedirects(response, reverse("attendance"))
        self.assertGreater(self.client.session.get_expiry_age(), 60 * 60 * 24 * 13)
        
        
    def test_new_lead_creates_notification(self):
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(reverse("applications"), {
            "full_name": "Соколова Мария",
            "birth_date": "",
            "age_text": "10 лет",
            "source": "VK",
            "phone": "79990000000",
            "trial_at": "",
            "trainer": "",
            "group": "",
            "status": Lead.Status.NEW,
            "comment": "",
        })

        self.assertRedirects(response, reverse("applications"))

        lead = Lead.objects.get(full_name="Соколова Мария")

        self.assertTrue(Notification.objects.filter(
            recipient=self.boss,
            actor=self.admin,
            kind=Notification.Kind.LEAD_CREATED,
            message__contains=lead.full_name,
            url=f"{reverse('applications')}?edit={lead.pk}",
            read_at__isnull=True,
        ).exists())

        self.assertTrue(Notification.objects.filter(
            recipient=self.senior,
            actor=self.admin,
            kind=Notification.Kind.LEAD_CREATED,
        ).exists())

        self.assertFalse(Notification.objects.filter(
            recipient=self.admin,
            kind=Notification.Kind.LEAD_CREATED,
        ).exists())
        
        def test_editing_lead_does_not_create_notification(self):
            lead = Lead.objects.create(
                full_name="Старая заявка",
                source="VK",
                status=Lead.Status.NEW,
            )

            self.client.login(username="admin", password="TestPass123!")

            response = self.client.post(
                f"{reverse('applications')}?edit={lead.pk}",
                {
                    "full_name": "Обновлённая заявка",
                    "birth_date": "",
                    "age_text": "",
                    "source": "VK",
                    "phone": "",
                    "trial_at": "",
                    "trainer": "",
                    "group": "",
                    "status": Lead.Status.NEW,
                    "comment": "Изменили комментарий",
                },
            )

            self.assertRedirects(response, reverse("applications"))

            lead.refresh_from_db()
            self.assertEqual(lead.full_name, "Обновлённая заявка")

            self.assertFalse(Notification.objects.filter(
                kind=Notification.Kind.LEAD_CREATED,
            ).exists())
