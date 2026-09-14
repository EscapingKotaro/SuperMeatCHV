from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.expire_trials import Command as ExpireTrialsCommand
from .models import (
    Attendance,
    AuditEvent,
    Child,
    Group,
    ManagerTask,
    Notification,
    Payment,
    Trainer,
    expire_trials,
)


class Tz2RemainingFunctionalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tz2-admin",
            password="TestPass123!",
            is_staff=True,
        )
        self.trainer = Trainer.objects.create(
            full_name="Основной Тренер",
        )
        self.group = Group.objects.create(
            name="Основная группа",
            trainer=self.trainer,
        )
        self.child = Child.objects.create(
            last_name="Иванова",
            first_name="Анна",
            birth_year=2016,
            group=self.group,
        )
        self.client.force_login(self.user)

    def test_due_task_reminder_appears_on_due_date_for_archived_child(self):
        today = timezone.localdate()
        task = ManagerTask.objects.create(
            title="Позвонить семье",
            child=self.child,
            assignee=self.user,
            created_by=self.user,
            due_date=today + timedelta(days=1),
        )

        self.client.get(reverse("notifications"))
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.user,
                event_key__startswith=f"task_due:{task.pk}:",
            ).exists()
        )

        self.child.archive(on_date=today)
        task.due_date = today
        task.save(update_fields=["due_date"])

        self.client.get(reverse("notifications"))
        reminder = Notification.objects.get(
            recipient=self.user,
            event_key=f"task_due:{task.pk}:{today.isoformat()}",
        )
        self.assertIsNone(reminder.resolved_at)
        self.assertIsNone(reminder.read_at)
        self.assertEqual(reminder.task_id, task.pk)
        self.assertEqual(
            reminder.url,
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertIn("Сегодня выполнить задачу", reminder.message)
        self.assertIn(str(self.child), reminder.message)

        self.client.get(reverse("notifications"))
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.user,
                event_key=f"task_due:{task.pk}:{today.isoformat()}",
            ).count(),
            1,
        )

        task.is_done = True
        task.save(update_fields=["is_done"])
        self.client.get(reverse("notifications"))

        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.resolved_at)

    def test_group_picker_shows_primary_trainer_first_and_collapses_others(self):
        primary_extra = Group.objects.create(
            name="Вторая группа основного тренера",
            trainer=self.trainer,
        )
        other_trainer = Trainer.objects.create(
            full_name="Другой Тренер",
        )
        other_group = Group.objects.create(
            name="Группа другого тренера",
            trainer=other_trainer,
        )

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        start = html.index("data-membership-group-picker")
        end = html.index("Требовать абонемент для этой группы", start)
        picker = html[start:end]

        primary_marker = (
            f'data-primary-trainer-group="{self.trainer.pk}"'
        )
        other_marker = (
            f'data-other-trainer-group="{other_trainer.pk}"'
        )

        self.assertIn(primary_marker, picker)
        self.assertIn(other_marker, picker)
        self.assertIn("Основной тренер", picker)
        self.assertIn(primary_extra.name, picker)
        self.assertIn(other_group.name, picker)
        self.assertIn("<details", picker)
        self.assertNotIn("<details open", picker)

        primary_pos = picker.index(primary_marker)
        primary_group_pos = picker.index(primary_extra.name, primary_pos)
        other_pos = picker.index(other_marker)
        other_group_pos = picker.index(other_group.name, other_pos)

        self.assertLess(primary_pos, primary_group_pos)
        self.assertLess(primary_group_pos, other_pos)
        self.assertLess(other_pos, other_group_pos)

    def test_unpaid_trial_archives_after_30_days_and_preserves_history(self):
        today = timezone.localdate()
        self.child.status = Child.Status.TRIAL
        self.child.trial_from = today - timedelta(days=30)
        self.child.save(update_fields=["status", "trial_from"])

        mark = Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=1),
            status=Attendance.Status.PRESENT,
        )

        too_early = Child.objects.create(
            last_name="Ранняя",
            first_name="Пробная",
            birth_year=2017,
            group=self.group,
            status=Child.Status.TRIAL,
            trial_from=today - timedelta(days=29),
        )

        paid = Child.objects.create(
            last_name="Оплаченная",
            first_name="Пробная",
            birth_year=2017,
            group=self.group,
        )
        Payment.objects.create(
            child=paid,
            amount=Decimal("1000"),
            date=today,
        )
        paid.status = Child.Status.TRIAL
        paid.trial_from = today - timedelta(days=30)
        paid.save(update_fields=["status", "trial_from"])

        self.assertEqual(expire_trials(today), 1)

        self.child.refresh_from_db()
        mark.refresh_from_db()
        too_early.refresh_from_db()
        paid.refresh_from_db()

        self.assertEqual(self.child.status, Child.Status.ARCHIVED)
        self.assertEqual(self.child.archived_at, today)
        self.assertEqual(self.child.departure_group_id, self.group.pk)
        self.assertEqual(self.child.departure_trainer_id, self.trainer.pk)
        self.assertEqual(mark.group_snapshot_id, self.group.pk)
        self.assertEqual(mark.trainer_snapshot_id, self.trainer.pk)

        self.assertEqual(too_early.status, Child.Status.TRIAL)
        self.assertEqual(paid.status, Child.Status.TRIAL)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="trial.expired",
                object_id=str(self.child.pk),
                description__icontains="архив",
            ).exists()
        )
        self.assertIn("30 дней", ExpireTrialsCommand.help)
        self.assertIn("архив", ExpireTrialsCommand.help.lower())
