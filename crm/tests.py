from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .intake_parser import parse_application
from .models import (
    Apparatus,
    ApparatusScore,
    Attendance,
    AuditEvent,
    Child,
    Competition,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    ManagerTask,
    Notification,
    Newcomer,
    Payment,
    RevenueTarget,
    Role,
    StaffProfile,
    Subscription,
    Tariff,
    ScheduleOverride,
    ScheduleSlot,
    Trainer,
    effective_class_dates,
    expire_trials,
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

    def test_attendance_creates_active_child_inline(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('attendance')}?group_id={self.group.pk}",
            {
                "action": "create_child",
                "last_name": "Петрова",
                "first_name": "Ева",
                "patronymic": "",
                "birth_date": "",
                "birth_year": "2016",
                "address": "",
                "parent_name": "",
                "parent_phone": "",
                "certificate_note": "",
                "group": str(self.group.pk),
                "discount_percent": "0",
                "note": "",
            },
        )

        child = Child.objects.get(
            last_name="Петрова",
            first_name="Ева",
        )

        self.assertEqual(child.group, self.group)
        self.assertEqual(child.status, Child.Status.ACTIVE)
        self.assertIsNone(child.trial_from)
        self.assertRedirects(
            response,
            f"{reverse('attendance')}?group_id={self.group.pk}",
        )

    def test_attendance_uses_inline_child_create_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "create_child": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'data-modal="child-create-modal"',
        )
        self.assertContains(
            response,
            'id="child-create-modal" class="modal open"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("child_create")}"',
        )
        self.assertNotContains(response, 'name="status"')
        self.assertNotContains(response, 'name="trial_from"')

    def test_legacy_child_create_get_redirects_to_attendance_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("child_create"),
            {
                "group_id": self.group.pk,
            },
        )

        self.assertRedirects(
            response,
            (
                f"{reverse('attendance')}"
                f"?create_child=1&group_id={self.group.pk}"
            ),
        )

    def test_child_card_subscription_links_open_payments_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse(
                "child_card",
                args=[self.child.pk],
            ),
        )

        expected = (
            f"{reverse('payments')}?child={self.child.pk}"
            "&new_subscription=1"
        )
        self.assertContains(
            response,
            expected,
            count=2,
        )
        self.assertNotContains(
            response,
            reverse(
                "add_subscription",
                args=[self.child.pk],
            ),
        )

    def test_legacy_child_create_invalid_post_stays_in_attendance_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_create"),
            {
                "last_name": "Петрова",
                "first_name": "",
                "birth_year": "2016",
                "group": str(self.group.pk),
                "discount_percent": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'id="child-create-modal" class="modal open"',
        )
        self.assertIn(
            "first_name",
            response.context["child_form"].errors,
        )
        self.assertTemplateUsed(response, "crm/attendance.html")

    def test_legacy_child_edit_get_redirects_to_card_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        target = (
            f"{reverse('child_card', args=[self.child.pk])}?edit=1"
        )
        response = self.client.get(
            reverse(
                "child_edit",
                args=[self.child.pk],
            ),
        )

        self.assertRedirects(response, target)
        modal = self.client.get(target)
        self.assertContains(
            modal,
            'id="child-edit-modal" class="modal open"',
        )

    def test_legacy_subscription_get_redirects_to_payments_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        target = (
            f"{reverse('payments')}?child={self.child.pk}"
            "&new_subscription=1"
        )
        response = self.client.get(
            reverse(
                "add_subscription",
                args=[self.child.pk],
            ),
        )

        self.assertRedirects(response, target)

    def test_legacy_subscription_invalid_post_redirects_to_payments_modal(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        target = (
            f"{reverse('payments')}?child={self.child.pk}"
            "&new_subscription=1"
        )
        response = self.client.post(
            reverse(
                "add_subscription",
                args=[self.child.pk],
            ),
            {},
        )

        self.assertRedirects(response, target)

    def test_legacy_trainer_form_gets_redirect_to_list_modals(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        create_target = f"{reverse('trainer_list')}?create=1"
        edit_target = (
            f"{reverse('trainer_list')}?edit={self.trainer.pk}"
        )

        self.assertRedirects(
            self.client.get(reverse("trainer_create")),
            create_target,
        )
        self.assertRedirects(
            self.client.get(
                reverse(
                    "trainer_edit",
                    args=[self.trainer.pk],
                ),
            ),
            edit_target,
        )

        self.assertContains(
            self.client.get(create_target),
            'id="trainer-modal" class="modal open"',
        )
        self.assertContains(
            self.client.get(edit_target),
            'id="trainer-modal" class="modal open"',
        )

    def test_legacy_group_form_gets_redirect_to_list_modals(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        create_target = f"{reverse('group_list')}?create=1"
        edit_target = (
            f"{reverse('group_list')}?edit={self.group.pk}"
        )

        self.assertRedirects(
            self.client.get(reverse("group_create")),
            create_target,
        )
        self.assertRedirects(
            self.client.get(
                reverse(
                    "group_edit",
                    args=[self.group.pk],
                ),
            ),
            edit_target,
        )

        create_page = self.client.get(create_target)
        edit_page = self.client.get(edit_target)
        self.assertContains(create_page, 'id="group-modal"')
        self.assertContains(create_page, 'class="modal open"')
        self.assertContains(edit_page, 'id="group-modal"')
        self.assertContains(edit_page, 'class="modal open"')

    def test_private_pages_require_login(self):
        response = self.client.get(reverse("expenses"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('expenses')}")

    def test_certificate_presence_uses_file_not_legacy_flag(self):
        self.child.certificate = ""
        self.child.certificate_ok = True
        self.child.save(
            update_fields=["certificate", "certificate_ok"],
        )

        self.assertFalse(self.child.has_certificate())

        self.child.certificate = "certificates/reference.jpg"
        self.child.certificate_ok = False
        self.child.save(
            update_fields=["certificate", "certificate_ok"],
        )

        self.assertTrue(self.child.has_certificate())

    def test_child_card_legacy_certificate_toggle_cannot_change_state(self):
        self.child.certificate = ""
        self.child.certificate_ok = False
        self.child.save(
            update_fields=["certificate", "certificate_ok"],
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {"action": "toggle_certificate"},
        )

        self.assertEqual(response.status_code, 200)

        self.child.refresh_from_db()
        self.assertFalse(self.child.certificate_ok)
        self.assertFalse(self.child.has_certificate())

    def test_role_access_to_boss_page(self):
        self.client.login(username="admin", password="TestPass123!")
        self.assertEqual(self.client.get(reverse("boss")).status_code, 403)
        self.client.logout()
        self.client.login(username="boss", password="TestPass123!")
        self.assertEqual(self.client.get(reverse("boss")).status_code, 200)

    def test_expenses_get_does_not_show_form_error(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(reverse("expenses"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Проверьте заполнение формы",
        )

    def test_invalid_expense_post_shows_form_error(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("expenses"),
            {
                "title": "",
                "category": Expense.Category.HOUSEHOLD,
                "amount": "",
                "date": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Проверьте заполнение формы",
        )

    def test_future_attendance_mark_is_rejected(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        future_date = timezone.localdate() + timedelta(days=1)

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": future_date.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertFalse(
            Attendance.objects.filter(
                child=self.child,
                date=future_date,
            ).exists()
        )

    def test_future_attendance_cells_are_read_only(self):
        today = timezone.localdate()
        future_date = today + timedelta(days=1)

        ScheduleSlot.objects.create(
            group=self.group,
            weekday=future_date.weekday(),
            start_time=time(18, 0),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        child_row = next(
            item
            for item in response.context["children_data"]
            if item["child"].pk == self.child.pk
        )
        future_entries = [
            item
            for item in child_row["attendance_entries"]
            if item["date"] > today
        ]

        self.assertTrue(future_entries)
        self.assertTrue(
            all(item["is_future"] for item in future_entries)
        )
        self.assertContains(response, 'aria-disabled="true"')

    def test_admin_can_create_expense(self):
        today = timezone.localdate()

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("expenses"),
            {
                "title": "Вода",
                "category": Expense.Category.HOUSEHOLD,
                "amount": "1250.50",
                "date": today.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('expenses')}?month={today:%Y-%m}",
        )

        self.assertTrue(
            Expense.objects.filter(
                title="Вода",
                created_by=self.admin,
            ).exists()
        )
        
        
    def test_admin_can_edit_own_expense(self):
        expense = Expense.objects.create(
            title="Вода",
            category=Expense.Category.HOUSEHOLD,
            amount=Decimal("1000"),
            date=timezone.localdate(),
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('expenses')}?edit={expense.pk}",
            {
                "title": "Вода и стаканы",
                "category": Expense.Category.HOUSEHOLD,
                "amount": "1500",
                "date": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)

        expense.refresh_from_db()

        self.assertEqual(
            expense.title,
            "Вода и стаканы",
        )

        self.assertEqual(
            expense.created_by,
            self.admin,
        )


    def test_admin_cannot_manage_other_expense(self):
        expense = Expense.objects.create(
            title="Инвентарь",
            category=Expense.Category.EQUIPMENT,
            amount=Decimal("3000"),
            date=timezone.localdate(),
            created_by=self.senior,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            f"{reverse('expenses')}?edit={expense.pk}"
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        response = self.client.post(
            reverse("expenses"),
            {
                "action": "delete",
                "expense_id": expense.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            Expense.objects.filter(
                pk=expense.pk,
            ).exists()
        )


    def test_senior_can_manage_any_expense(self):
        expense = Expense.objects.create(
            title="Ремонт",
            category=Expense.Category.REPAIR,
            amount=Decimal("5000"),
            date=timezone.localdate(),
            created_by=self.admin,
        )

        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('expenses')}?edit={expense.pk}",
            {
                "title": "Ремонт зеркала",
                "category": Expense.Category.REPAIR,
                "amount": "5500",
                "date": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        expense.refresh_from_db()

        self.assertEqual(
            expense.title,
            "Ремонт зеркала",
        )

        self.assertEqual(
            expense.created_by,
            self.admin,
        )

        response = self.client.post(
            reverse("expenses"),
            {
                "action": "delete",
                "expense_id": expense.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Expense.objects.filter(
                pk=expense.pk,
            ).exists()
        )


    def test_expenses_filter_by_month_and_category(self):
        today = timezone.localdate()
        previous_month = (
            today.replace(day=1)
            - timedelta(days=1)
        )

        household = Expense.objects.create(
            title="Вода",
            category=Expense.Category.HOUSEHOLD,
            amount=Decimal("1000"),
            date=today,
            created_by=self.admin,
        )

        Expense.objects.create(
            title="Ремонт",
            category=Expense.Category.REPAIR,
            amount=Decimal("2000"),
            date=today,
            created_by=self.admin,
        )

        Expense.objects.create(
            title="Старый расход",
            category=Expense.Category.HOUSEHOLD,
            amount=Decimal("3000"),
            date=previous_month,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("expenses"),
            {
                "month": today.strftime("%Y-%m"),
                "category": Expense.Category.HOUSEHOLD,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            list(response.context["expenses"]),
            [household],
        )

        self.assertEqual(
            response.context["total"],
            Decimal("1000"),
        )

        
    def test_notifications_are_read_only_after_explicit_action(self):
        notification = Notification.objects.create(
            recipient=self.admin,
            actor=self.boss,
            kind=Notification.Kind.TASK_CREATED,
            message="Новая задача",
        )

        self.client.login(username="admin", password="TestPass123!")
        self.client.get(reverse("notifications"))

        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)
        self.client.post(reverse("notifications"), {"action": "mark_read"})
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

    def test_blank_score_differs_from_zero(self):
        competition = Competition.objects.create(
            name="Кубок",
            date=timezone.localdate(),
        )

        apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
            order=0,
        )

        other = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
        )

        first = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        second = CompetitionEntry.objects.create(
            child=other,
            competition=competition,
            category="2015",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{first.pk}_{apparatus.pk}": "",
                f"score_{second.pk}_{apparatus.pk}": "0",
            },
        )

        self.assertEqual(response.status_code, 302)

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertIsNone(first.place)
        self.assertEqual(second.place, 1)

        self.assertIsNone(
            ApparatusScore.objects.get(
                entry=first,
                apparatus=apparatus,
            ).points
        )

        self.assertEqual(
            ApparatusScore.objects.get(
                entry=second,
                apparatus=apparatus,
            ).points,
            Decimal("0.000"),
        )

        export = self.client.get(
            reverse(
                "competition_export",
                args=[competition.pk],
            )
        )

        self.assertEqual(export.status_code, 200)


    def test_invalid_score_does_not_overwrite_saved_score(self):
        competition = Competition.objects.create(
            name="Кубок",
            date=timezone.localdate(),
        )

        apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
        )

        entry = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        score = ApparatusScore.objects.create(
            entry=entry,
            apparatus=apparatus,
            points=Decimal("9.500"),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{entry.pk}_{apparatus.pk}": "9,5а",
            },
        )

        self.assertEqual(response.status_code, 200)

        score.refresh_from_db()

        self.assertEqual(
            score.points,
            Decimal("9.500"),
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{entry.pk}_{apparatus.pk}": "-1",
            },
        )

        self.assertEqual(response.status_code, 200)

        score.refresh_from_db()

        self.assertEqual(
            score.points,
            Decimal("9.500"),
        )


    def test_competition_places_support_ties_and_categories(self):
        competition = Competition.objects.create(
            name="Кубок",
            date=timezone.localdate(),
        )

        apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
        )

        children = [
            self.child,
            Child.objects.create(
                last_name="Петрова",
                first_name="Мария",
                birth_year=2015,
                group=self.group,
            ),
            Child.objects.create(
                last_name="Сидорова",
                first_name="Анна",
                birth_year=2015,
                group=self.group,
            ),
            Child.objects.create(
                last_name="Орлова",
                first_name="Ева",
                birth_year=2016,
                group=self.group,
            ),
        ]

        entries = [
            CompetitionEntry.objects.create(
                child=children[0],
                competition=competition,
                category="2015",
            ),
            CompetitionEntry.objects.create(
                child=children[1],
                competition=competition,
                category="2015",
            ),
            CompetitionEntry.objects.create(
                child=children[2],
                competition=competition,
                category="2015",
            ),
            CompetitionEntry.objects.create(
                child=children[3],
                competition=competition,
                category="2016",
            ),
        ]

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{entries[0].pk}_{apparatus.pk}": "10",
                f"score_{entries[1].pk}_{apparatus.pk}": "10",
                f"score_{entries[2].pk}_{apparatus.pk}": "9",
                f"score_{entries[3].pk}_{apparatus.pk}": "5",
            },
        )

        self.assertEqual(response.status_code, 302)

        for entry in entries:
            entry.refresh_from_db()

        self.assertEqual(entries[0].place, 1)
        self.assertEqual(entries[1].place, 1)
        self.assertEqual(entries[2].place, 3)
        self.assertEqual(entries[3].place, 1)


    def test_competition_entry_can_be_edited_and_deleted(self):
        competition = Competition.objects.create(
            name="Кубок",
            date=timezone.localdate(),
        )

        apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
        )

        other = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
        )

        first = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        second = CompetitionEntry.objects.create(
            child=other,
            competition=competition,
            category="2015",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{first.pk}_{apparatus.pk}": "10",
                f"score_{second.pk}_{apparatus.pk}": "9",
            },
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_entry",
                "entry_id": first.pk,
                "entry-child": self.child.pk,
                "entry-category": "2016",
                "entry-rank": "2 юн.",
            },
        )

        self.assertEqual(response.status_code, 302)

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(first.category, "2016")
        self.assertEqual(first.rank, "2 юн.")
        self.assertEqual(first.place, 1)

        self.assertEqual(second.place, 1)

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "delete_entry",
                "entry_id": first.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            CompetitionEntry.objects.filter(
                pk=first.pk,
            ).exists()
        )


    def test_adding_apparatus_invalidates_places_and_delete_recalculates(self):
        competition = Competition.objects.create(
            name="Кубок",
            date=timezone.localdate(),
        )

        first_apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
            order=0,
        )

        entry = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_scores",
                f"score_{entry.pk}_{first_apparatus.pk}": "10",
            },
        )

        entry.refresh_from_db()
        self.assertEqual(entry.place, 1)

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "save_apparatus",
                "apparatus-name": "Брусья",
            },
        )

        self.assertEqual(response.status_code, 302)

        second_apparatus = Apparatus.objects.get(
            competition=competition,
            name="Брусья",
        )

        self.assertEqual(
            second_apparatus.order,
            1,
        )

        new_score = ApparatusScore.objects.get(
            entry=entry,
            apparatus=second_apparatus,
        )

        self.assertIsNone(new_score.points)

        entry.refresh_from_db()
        self.assertIsNone(entry.place)

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "delete_apparatus",
                "apparatus_id": second_apparatus.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        entry.refresh_from_db()

        self.assertEqual(entry.place, 1)


    def test_competition_can_be_deleted_with_related_results(self):
        competition = Competition.objects.create(
            name="Удаляемый кубок",
            date=timezone.localdate(),
        )

        apparatus = Apparatus.objects.create(
            competition=competition,
            name="Прыжок",
        )

        entry = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        score = ApparatusScore.objects.create(
            entry=entry,
            apparatus=apparatus,
            points=Decimal("9"),
        )

        competition_id = competition.pk
        apparatus_id = apparatus.pk
        entry_id = entry.pk
        score_id = score.pk

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            f"{reverse('competitions')}?competition={competition.pk}",
            {
                "action": "delete_competition",
                "competition_id": competition.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("competitions"),
        )

        self.assertFalse(
            Competition.objects.filter(
                pk=competition_id,
            ).exists()
        )

        self.assertFalse(
            Apparatus.objects.filter(
                pk=apparatus_id,
            ).exists()
        )

        self.assertFalse(
            CompetitionEntry.objects.filter(
                pk=entry_id,
            ).exists()
        )

        self.assertFalse(
            ApparatusScore.objects.filter(
                pk=score_id,
            ).exists()
        )


    def test_child_card_links_to_competition(self):
        competition = Competition.objects.create(
            name="Кубок Москвы",
            date=timezone.localdate(),
            is_internal=False,
        )

        CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse(
                "child_card",
                args=[self.child.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            (
                f"{reverse('competitions')}"
                f"?competition={competition.pk}"
            ),
        )

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

    def test_parser_matches_vk_sample_from_spec(self):
        raw = (
            "Новая заявка по форме: Спартак дети 13.03 об вопросы\n"
            "Дата отправки: 2026-08-31 10:16:47 (МСК)\n"
            "Имя: Дмитрий\n"
            "Телефон: +79067849503\n"
            "Вопрос: Имя и возраст ребёнка?\n"
            "Ответ: Возраст 10 лет\n"
            "Вопрос: Удобное время для звонка?\n"
            "Ответ: Пользователь предпочел не отвечать на данный вопрос\n"
            "Переход с рекламного объявления: "
            "https://ads.vk.ru/hq/dashboard/stats/ad/overview/233830557\n"
            "Кампания: ЛФ 01.07(24115836)\n"
            "Группа: гео список м. 30-40 км т5. крео.13(151328340)\n"
            "Объявление: т5 крео 13(233830557)"
        )

        parsed = parse_application(raw)

        self.assertEqual(parsed["full_name"], "Дмитрий")
        self.assertEqual(parsed["phone"], "+79067849503")
        self.assertEqual(parsed["age_text"], "10")
        self.assertEqual(parsed["source"], "VK Реклама")
        self.assertEqual(
            timezone.localtime(parsed["submitted_at"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "2026-08-31 10:16:47",
        )
        self.assertIn(
            "Удобное время для звонка: Пользователь предпочел не отвечать",
            parsed["comment"],
        )
        self.assertIn("Кампания: ЛФ 01.07(24115836)", parsed["comment"])
        self.assertIn(
            "Группа объявлений: гео список м. 30-40 км",
            parsed["comment"],
        )
        self.assertIn("Объявление: т5 крео 13(233830557)", parsed["comment"])
        self.assertIn("Исходная заявка:", parsed["comment"])

    def test_imported_application_uses_original_submission_time(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        raw = (
            "Дата отправки: 2026-08-31 10:16:47 (МСК)\n"
            "Имя: Дмитрий\n"
            "Телефон: +79067849503\n"
            "Переход с рекламного объявления: "
            "https://ads.vk.ru/hq/dashboard/stats/ad/overview/233830557\n"
            "Кампания: ЛФ 01.07(24115836)"
        )

        response = self.client.post(
            reverse("applications"),
            {
                "action": "import_raw",
                "raw_application": raw,
            },
        )

        self.assertRedirects(response, reverse("applications"))
        lead = Lead.objects.get(full_name="Дмитрий")

        self.assertTrue(lead.imported_from_ad)
        self.assertEqual(lead.source, "VK Реклама")
        self.assertEqual(
            timezone.localtime(lead.created_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "2026-08-31 10:16:47",
        )
        self.assertIn("Кампания: ЛФ 01.07(24115836)", lead.comment)

    def test_parser_maps_website_birth_date_and_trial_datetime(self):
        parsed = parse_application(
            "Имя: Анна Петрова\n"
            "Телефон: 8 (999) 123-45-67\n"
            "Возраст: 7 лет\n"
            "Источник: Сайт\n"
            "Дата рождения: 2019-03-14\n"
            "Дата и время пробного занятия: 2026-09-12 18:30"
        )

        self.assertEqual(parsed["full_name"], "Анна Петрова")
        self.assertEqual(parsed["phone"], "+79991234567")
        self.assertEqual(parsed["age_text"], "7")
        self.assertEqual(parsed["source"], "Сайт")
        self.assertEqual(
            parsed["birth_date"].isoformat(),
            "2019-03-14",
        )
        self.assertEqual(
            timezone.localtime(parsed["trial_at"]).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "2026-09-12 18:30",
        )

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
                # Рядовой менеджер не может назначить задачу коллеге:
                # crafted POST должен быть принудительно привязан к нему самому.
                "assignee": self.senior.pk,
                "scheduled_at": start_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "scheduled_end_at": end_at.strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "due_date": start_at.date().isoformat(),
            },
        )

        today = timezone.localdate()
        month_start = today.replace(day=1)
        
        self.assertRedirects(
            response,
            f"{reverse('calendar')}?start={month_start.isoformat()}&day={today.isoformat()}&scope=mine&state=open"
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

        today = timezone.localdate()
        month_start = today.replace(day=1)

        self.assertRedirects(
            response,
            f"{reverse('calendar')}?start={month_start.isoformat()}&day={today.isoformat()}&scope=mine&state=open",
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


    def test_manager_cannot_reopen_completed_task(self):
        task = ManagerTask.objects.create(
            title="Уже выполнено",
            assignee=self.admin,
            created_by=self.boss,
            is_done=True,
            done_at=timezone.now(),
            completed_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("notifications"),
            {"task_id": task.pk},
        )

        self.assertEqual(response.status_code, 403)
        task.refresh_from_db()
        self.assertTrue(task.is_done)


    def test_boss_can_return_completed_task_to_work(self):
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
            username="boss",
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


    def test_manager_calendar_forces_personal_open_scope(self):
        today = timezone.localdate()

        own = ManagerTask.objects.create(
            title="Моя активная задача",
            assignee=self.admin,
            created_by=self.boss,
            due_date=today,
        )
        common = ManagerTask.objects.create(
            title="Общая активная задача",
            assignee=None,
            created_by=self.boss,
            due_date=today,
        )
        foreign = ManagerTask.objects.create(
            title="Чужая активная задача",
            assignee=self.senior,
            created_by=self.boss,
            due_date=today,
        )
        completed = ManagerTask.objects.create(
            title="Моя выполненная задача",
            assignee=self.admin,
            created_by=self.boss,
            due_date=today,
            is_done=True,
            done_at=timezone.now(),
            completed_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("calendar"),
            {
                "start": today.replace(day=1).isoformat(),
                "day": today.isoformat(),
                "scope": "all",
                "state": "all",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scope"], "mine")
        self.assertEqual(response.context["state"], "open")
        self.assertFalse(response.context["can_manage_team_tasks"])

        selected_ids = {
            task.pk for task in response.context["selected_tasks"]
        }
        self.assertEqual(selected_ids, {own.pk, common.pk})
        self.assertNotIn(foreign.pk, selected_ids)
        self.assertNotIn(completed.pk, selected_ids)

        edit_response = self.client.get(
            reverse("calendar"),
            {"edit": completed.pk},
        )
        self.assertEqual(edit_response.status_code, 403)

        self.assertContains(response, "data-calendar-sidebar")
        self.assertContains(
            response,
            "xl:grid-cols-[minmax(0,1fr)_18rem]",
        )
        self.assertNotContains(response, "На смене:")
        self.assertNotContains(response, "Готовые")


    def test_boss_calendar_can_view_completed_team_tasks(self):
        today = timezone.localdate()
        completed = ManagerTask.objects.create(
            title="Выполненная задача команды",
            assignee=self.admin,
            created_by=self.boss,
            due_date=today,
            is_done=True,
            done_at=timezone.now(),
            completed_by=self.admin,
        )

        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("calendar"),
            {
                "start": today.replace(day=1).isoformat(),
                "day": today.isoformat(),
                "scope": "all",
                "state": "done",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_manage_team_tasks"])
        self.assertEqual(response.context["state"], "done")
        self.assertIn(completed, response.context["selected_tasks"])
        self.assertContains(response, "Готовые")


    def test_admin_role_inherits_boss_task_permissions(self):
        user_model = get_user_model()
        root = user_model.objects.create_user(
            "root-admin",
            password="TestPass123!",
            is_staff=True,
        )
        StaffProfile.objects.create(
            user=root,
            role=Role.ADMIN,
        )

        task = ManagerTask.objects.create(
            title="Чужая задача для проверки ADMIN",
            assignee=self.admin,
            created_by=self.boss,
            due_date=timezone.localdate(),
        )

        self.client.login(
            username="root-admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("calendar"),
            {
                "action": "delete",
                "task_id": task.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ManagerTask.objects.filter(pk=task.pk).exists()
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

    def test_attendance_skips_days_without_classes(self):
        today = timezone.localdate()
        ref_date = today + timedelta(
            days=(7 - today.weekday()) % 7,
        )

        for weekday in (0, 2):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )

        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=60),
            sessions_total=8,
            price=Decimal("5000"),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": ref_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        week_data = response.context["week_data"]
        self.assertGreaterEqual(len(week_data), 6)
        self.assertLessEqual(len(week_data), 10)
        self.assertTrue(
            all(
                item["date"].weekday() in {0, 2}
                for item in week_data
            )
        )
        self.assertContains(
            response,
            f"{len(week_data)} занятий",
        )
        self.assertNotContains(
            response,
            "8 дней",
        )

    def test_attendance_sessions_sort_uses_completed_sessions(self):
        ScheduleSlot.objects.create(group=self.group, weekday=0, start_time=time(16))
        today = timezone.localdate()
        other = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
        )

        for child in (self.child, other):
            Subscription.objects.create(
                child=child,
                start_date=today - timedelta(days=10),
                end_date=today + timedelta(days=20),
                sessions_total=8,
                price=Decimal("5000"),
            )

        for offset in (3, 2, 1):
            Attendance.objects.create(
                child=self.child,
                date=today - timedelta(days=offset),
                status=Attendance.Status.PRESENT,
            )

        Attendance.objects.create(
            child=other,
            date=today - timedelta(days=1),
            status=Attendance.Status.PRESENT,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": today.isoformat(),
                "sort": "sessions",
            },
        )

        ordered_ids = [
            item["child"].pk
            for item in response.context["children_data"]
        ]
        self.assertEqual(
            ordered_ids[:2],
            [self.child.pk, other.pk],
        )

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
                      
    def test_newcomer_trial_creates_notification(self):
        trial_at = timezone.now() + timedelta(days=1)

        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(reverse("newcomers"), {
            "full_name": "Петрова Алиса",
            "birth_date": "",
            "age_text": "9 лет",
            "phone": "79990000001",
            "source": "VK",
            "trial_at": trial_at.strftime("%Y-%m-%dT%H:%M"),
            "trainer": "",
            "group": "",
            "attended": "",
            "paid": "",
            "lesson_cancelled": "",
            "comment": "",
        })

        self.assertRedirects(response, reverse("newcomers"))

        newcomer = Newcomer.objects.get(full_name="Петрова Алиса")

        self.assertTrue(Notification.objects.filter(
            recipient=self.boss,
            actor=self.admin,
            kind=Notification.Kind.TRIAL_SCHEDULED,
            url=f"{reverse('newcomers')}?edit={newcomer.pk}",
        ).exists())

    def test_newcomer_paid_flag_is_not_user_editable(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("newcomers"),
            {"create": "1"},
        )

        self.assertNotContains(
            response,
            'name="paid"',
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "full_name": "Ручная оплата запрещена",
                "paid": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("newcomers"),
        )

        newcomer = Newcomer.objects.get(
            full_name="Ручная оплата запрещена",
        )

        self.assertFalse(
            newcomer.paid,
        )

    def test_real_payment_marks_newcomer_paid_and_promotes_trial_child(self):
        newcomer = Newcomer.objects.create(
            full_name="Петров Иван",
            group=self.group,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "convert",
                "newcomer_id": newcomer.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("payments"),
        )

        newcomer.refresh_from_db()
        child = newcomer.child

        self.assertEqual(
            child.status,
            Child.Status.TRIAL,
        )
        self.assertFalse(
            newcomer.paid,
        )

        payments_page = self.client.get(
            reverse("payments"),
        )

        self.assertIn(
            child,
            list(payments_page.context["children"]),
        )

        response = self.client.post(
            reverse("payments"),
            {
                "action": "payment",
                "child_id": child.pk,
                "amount": "1500",
                "date": timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("payments"),
        )

        child.refresh_from_db()
        newcomer.refresh_from_db()

        self.assertEqual(
            child.status,
            Child.Status.ACTIVE,
        )
        self.assertIsNone(
            child.trial_from,
        )
        self.assertTrue(
            newcomer.paid,
        )
        self.assertTrue(
            Payment.objects.filter(
                child=child,
                amount=Decimal("1500"),
            ).exists()
        )

    def test_editing_newcomer_without_trial_change_does_not_notify(self):
        trial_at = timezone.now() + timedelta(days=1)

        newcomer = Newcomer.objects.create(
            full_name="Иванова Ева",
            trial_at=trial_at,
        )

        self.client.login(username="admin", password="TestPass123!")

        self.client.post(
            f"{reverse('newcomers')}?edit={newcomer.pk}",
            {
                "full_name": "Иванова Ева",
                "birth_date": "",
                "age_text": "",
                "phone": "79990000002",
                "source": "VK",
                "trial_at": timezone.localtime(trial_at).strftime("%Y-%m-%dT%H:%M"),
                "trainer": "",
                "group": "",
                "attended": "",
                "paid": "",
                "lesson_cancelled": "",
                "comment": "Изменили комментарий",
            },
        )

        self.assertFalse(Notification.objects.filter(
            kind=Notification.Kind.TRIAL_SCHEDULED,
        ).exists())
        
    def test_cancelled_subscription_does_not_affect_current_state(self):
        today = timezone.localdate()

        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=10),
            sessions_total=8,
            price=Decimal("5600"),
            promo="Скидка 10%",
            is_active=True,
        )

        self.assertEqual(
            self.child.sessions_left(),
            8,
        )

        self.assertEqual(
            self.child.nearest_expiry(),
            subscription.end_date,
        )

        self.assertEqual(
            list(self.child.active_promos()),
            [
                (
                    "Скидка 10%",
                    subscription.end_date,
                )
            ],
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("payments"),
            {
                "action": "cancel_subscription",
                "subscription_id": subscription.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("payments"),
        )

        subscription.refresh_from_db()

        self.assertFalse(
            subscription.is_active
        )

        self.assertEqual(
            self.child.sessions_left(),
            0,
        )

        self.assertIsNone(
            self.child.nearest_expiry()
        )

        self.assertEqual(
            list(self.child.active_promos()),
            [],
        )
        
    def test_statistics_forecast_ignores_cancelled_subscription(self):
        today = timezone.localdate()
        next_month = (
            today.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_end = next_month - timedelta(days=1)

        active_child = Child.objects.create(
            last_name="Активная",
            first_name="Анна",
            birth_year=2015,
            group=self.group,
            status=Child.Status.ACTIVE,
        )

        cancelled_child = Child.objects.create(
            last_name="Отменённая",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
            status=Child.Status.ACTIVE,
        )

        Subscription.objects.create(
            child=active_child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )

        Subscription.objects.create(
            child=cancelled_child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("9000"),
            is_active=False,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {
                "month": today.strftime("%Y-%m"),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["potential"],
            Decimal("6000"),
        )
        


    def test_month_reports_normalize_selected_day_to_whole_month(self):
        today = timezone.localdate()

        selected_day = today.replace(
            day=min(15, today.day),
        )

        first_day = selected_day.replace(
            day=1,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {
                "month": selected_day.isoformat(),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["month_start"],
            first_day,
        )
        
    def test_expenses_page_has_monthly_category_summary(self):
        today = timezone.localdate()

        Expense.objects.create(
            title="Вода",
            category=Expense.Category.HOUSEHOLD,
            amount=Decimal("1000"),
            date=today,
            created_by=self.admin,
        )

        Expense.objects.create(
            title="Мячи",
            category=Expense.Category.EQUIPMENT,
            amount=Decimal("3000"),
            date=today,
            created_by=self.admin,
        )

        Expense.objects.create(
            title="Ещё инвентарь",
            category=Expense.Category.EQUIPMENT,
            amount=Decimal("2000"),
            date=today,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("expenses"),
            {
                "month": today.strftime("%Y-%m"),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["monthly_total"],
            Decimal("6000"),
        )

        self.assertEqual(
            response.context["monthly_operations"],
            3,
        )

        categories = {
            row["category"]: row
            for row in response.context["category_rows"]
        }

        self.assertEqual(
            categories[Expense.Category.HOUSEHOLD]["total"],
            Decimal("1000"),
        )

        self.assertEqual(
            categories[Expense.Category.HOUSEHOLD]["operations"],
            1,
        )

        self.assertEqual(
            categories[Expense.Category.EQUIPMENT]["total"],
            Decimal("5000"),
        )

        self.assertEqual(
            categories[Expense.Category.EQUIPMENT]["operations"],
            2,
        )

    def test_statistics_excludes_archived_and_lost_children_from_group_metrics(self):
        today = timezone.localdate()

        trial_child = Child.objects.create(
            last_name="Пробная",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
            status=Child.Status.TRIAL,
            trial_from=today,
        )

        archived_child = Child.objects.create(
            last_name="Архивная",
            first_name="Елена",
            birth_year=2015,
            group=self.group,
            status=Child.Status.ARCHIVED,
            archived_at=today,
        )

        lost_child = Child.objects.create(
            last_name="Потерянная",
            first_name="Ольга",
            birth_year=2015,
            group=self.group,
            status=Child.Status.LOST,
            archived_at=today,
        )

        Attendance.objects.create(
            child=archived_child,
            date=today,
            status=Attendance.Status.PRESENT,
        )

        Attendance.objects.create(
            child=lost_child,
            date=today,
            status=Attendance.Status.ABSENT,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {
                "month": today.isoformat(),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        group_stats = next(
            row
            for row in response.context["groups_stats"]
            if row["group"].pk == self.group.pk
        )

        self.assertEqual(
            group_stats["kids"],
            2,
        )

        self.assertEqual(
            group_stats["present"],
            0,
        )

        self.assertEqual(
            group_stats["absent"],
            0,
        )
        
        
    def test_statistics_get_does_not_write_attendance_snapshots(self):
        today = timezone.localdate()

        attendance = Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        attendance.refresh_from_db()
        self.assertIsNone(attendance.group_snapshot)
        self.assertIsNone(attendance.trainer_snapshot)
        self.assertIsNone(attendance.salary_rate_snapshot)

        self.client.logout()
        self.client.login(
            username="senior",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("salaries"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        attendance.refresh_from_db()
        self.assertIsNone(attendance.group_snapshot)
        self.assertIsNone(attendance.trainer_snapshot)
        self.assertIsNone(attendance.salary_rate_snapshot)

    def test_transferred_child_old_mark_does_not_inflate_current_group_stats(self):
        today = timezone.localdate()

        other_trainer = Trainer.objects.create(
            full_name="Другой тренер",
        )
        other_group = Group.objects.create(
            name="Другая группа",
            trainer=other_trainer,
        )

        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
            salary_rate_snapshot=self.group.salary_rate,
            status=Attendance.Status.PRESENT,
        )

        self.child.group = other_group
        self.child.save(update_fields=["group"])

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        old_group_stats = next(
            row
            for row in response.context["groups_stats"]
            if row["group"].pk == self.group.pk
        )
        new_group_stats = next(
            row
            for row in response.context["groups_stats"]
            if row["group"].pk == other_group.pk
        )

        self.assertEqual(old_group_stats["present"], 0)
        self.assertEqual(new_group_stats["present"], 0)

    def test_future_subscription_is_not_pending_renewal(self):
        today = timezone.localdate()
        future_start = (
            today.replace(day=28)
            + timedelta(days=40)
        ).replace(day=1)
        future_end = future_start + timedelta(days=20)

        Subscription.objects.create(
            child=self.child,
            start_date=future_start,
            end_date=future_end,
            sessions_total=8,
            price=Decimal("7000"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("payments"),
            {"month": future_end.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], [])
        self.assertEqual(response.context["expected"], Decimal("0"))

    def test_statistics_and_prepayments_use_same_forecast_source(self):
        today = timezone.localdate()
        next_month = (
            today.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_end = next_month - timedelta(days=1)

        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("6500"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        month = today.strftime("%Y-%m")

        statistics = self.client.get(
            reverse("statistics"),
            {"month": month},
        )
        prepayments = self.client.get(
            reverse("payments"),
            {"month": month},
        )

        self.assertEqual(statistics.status_code, 200)
        self.assertEqual(prepayments.status_code, 200)
        self.assertEqual(
            statistics.context["expected"],
            prepayments.context["expected"],
        )
        self.assertEqual(
            statistics.context["potential"],
            Decimal(statistics.context["revenue_month"])
            + prepayments.context["expected"],
        )

    def test_boss_target_for_other_month_does_not_move_current_target(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        next_month = (
            current_month
            + timedelta(days=32)
        ).replace(day=1)

        current_target = RevenueTarget.objects.create(
            month=current_month,
            amount=Decimal("500000"),
            set_by=self.boss,
        )

        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("boss"),
            {
                "action": "set_target",
                "target-month": next_month.strftime("%Y-%m"),
                "target-amount": "600000",
            },
        )

        self.assertRedirects(response, reverse("boss"))

        current_target.refresh_from_db()
        self.assertEqual(
            current_target.amount,
            Decimal("500000"),
        )
        self.assertEqual(
            RevenueTarget.objects.get(month=next_month).amount,
            Decimal("600000"),
        )

    def test_inactive_trainer_with_departure_is_kept_in_statistics(self):
        today = timezone.localdate()

        inactive_trainer = Trainer.objects.create(
            full_name="Бывший тренер",
            is_active=False,
        )

        Child.objects.create(
            last_name="Ушедшая",
            first_name="Спортсменка",
            birth_year=2014,
            group=self.group,
            status=Child.Status.LOST,
            archived_at=today,
            departure_trainer=inactive_trainer,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        trainer_row = next(
            row
            for row in response.context["trainers_stats"]
            if row["trainer"].pk == inactive_trainer.pk
        )

        self.assertEqual(trainer_row["left"], 1)

    def test_salary_pages_require_senior_role(self):
        today = timezone.localdate()

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        self.assertEqual(
            self.client.get(
                reverse("salaries"),
                {"month": today.strftime("%Y-%m")},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("salaries_export"),
                {"month": today.strftime("%Y-%m")},
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
                reverse("salaries"),
                {"month": today.strftime("%Y-%m")},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("salaries_export"),
                {"month": today.strftime("%Y-%m")},
            ).status_code,
            200,
        )

    def test_statistics_control_scenario_matches_manual_numbers(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        previous_day = month_start - timedelta(days=1)

        previous_created_at = timezone.make_aware(
            datetime.combine(previous_day, time(12, 0))
        )
        current_created_at = timezone.make_aware(
            datetime.combine(month_start, time(12, 0))
        )

        # Базовый ребёнок существовал до выбранного месяца.
        Child.objects.filter(pk=self.child.pk).update(
            created_at=previous_created_at,
        )

        active_new = Child.objects.create(
            last_name="Новая",
            first_name="Активная",
            birth_year=2015,
            group=self.group,
            status=Child.Status.ACTIVE,
        )
        trial_new = Child.objects.create(
            last_name="Новая",
            first_name="Пробная",
            birth_year=2016,
            group=self.group,
            status=Child.Status.TRIAL,
            trial_from=today,
        )
        lost_new = Child.objects.create(
            last_name="Новая",
            first_name="Ушедшая",
            birth_year=2014,
            group=self.group,
            status=Child.Status.LOST,
            archived_at=today,
            departure_group=self.group,
            departure_trainer=self.trainer,
        )
        Child.objects.filter(
            pk__in=[
                active_new.pk,
                trial_new.pk,
                lost_new.pk,
            ],
        ).update(created_at=current_created_at)

        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )

        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
            salary_rate_snapshot=Decimal("300"),
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            child=active_new,
            date=today,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
            salary_rate_snapshot=Decimal("300"),
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            child=trial_new,
            date=today,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
            salary_rate_snapshot=Decimal("300"),
            status=Attendance.Status.ABSENT,
        )

        Payment.objects.create(
            child=self.child,
            amount=Decimal("1000"),
            date=today,
            created_by=self.admin,
        )
        Payment.objects.create(
            child=active_new,
            amount=Decimal("2000"),
            date=today,
            created_by=self.admin,
        )
        Expense.objects.create(
            title="Контрольный расход",
            category=Expense.Category.HOUSEHOLD,
            amount=Decimal("500"),
            date=today,
            created_by=self.admin,
        )
        target = RevenueTarget.objects.create(
            month=month_start,
            amount=Decimal("10000"),
            set_by=self.boss,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        statistics = self.client.get(
            reverse("statistics"),
            {"month": month_start.strftime("%Y-%m")},
        )
        self.assertEqual(statistics.status_code, 200)

        # Контрольные цифры считаются вручную из набора выше:
        # 2 ACTIVE + 1 TRIAL = 3 текущих спортсмена.
        self.assertEqual(statistics.context["total_children"], 3)
        self.assertEqual(statistics.context["active_children"], 2)

        # В этом месяце созданы ACTIVE, TRIAL и LOST.
        self.assertEqual(statistics.context["new_count"], 3)
        # Остался из новых только ACTIVE; пробник ещё не считается
        # конвертированным спортсменом.
        self.assertEqual(statistics.context["new_kept"], 1)
        self.assertEqual(statistics.context["left_count"], 1)

        self.assertEqual(
            statistics.context["revenue_to_date"],
            Decimal("3000"),
        )
        self.assertEqual(
            statistics.context["revenue_month"],
            Decimal("3000"),
        )
        self.assertEqual(
            statistics.context["expected"],
            Decimal("0"),
        )
        self.assertEqual(
            statistics.context["potential"],
            Decimal("3000"),
        )
        self.assertEqual(statistics.context["target"], target)
        self.assertEqual(
            statistics.context["expenses_month"],
            Decimal("500"),
        )

        held_sessions = sum(
            1
            for offset in range((today - month_start).days + 1)
            if (
                month_start
                + timedelta(days=offset)
            ).weekday() == today.weekday()
        )
        expected_capacity = 3 * held_sessions
        expected_attendance = round(
            2 * 100 / expected_capacity
        )

        group_row = next(
            row
            for row in statistics.context["groups_stats"]
            if row["group"].pk == self.group.pk
        )
        self.assertEqual(group_row["kids"], 3)
        self.assertEqual(group_row["present"], 2)
        self.assertEqual(group_row["absent"], 1)
        self.assertEqual(group_row["sessions"], held_sessions)
        self.assertEqual(group_row["capacity"], expected_capacity)
        self.assertEqual(
            group_row["attendance_pct"],
            expected_attendance,
        )

        trainer_row = next(
            row
            for row in statistics.context["trainers_stats"]
            if row["trainer"].pk == self.trainer.pk
        )
        self.assertEqual(trainer_row["present"], 2)
        self.assertEqual(trainer_row["left"], 1)
        self.assertEqual(
            trainer_row["attendance_pct"],
            expected_attendance,
        )

        # Таблица продлений использует тот же источник прогноза.
        prepayments = self.client.get(
            reverse("payments"),
            {"month": month_start.strftime("%Y-%m")},
        )
        self.assertEqual(prepayments.status_code, 200)
        self.assertEqual(
            prepayments.context["expected"],
            Decimal("0"),
        )

        # ЗП: два фактических посещения по 300 ₽.
        self.client.logout()
        self.client.login(
            username="senior",
            password="TestPass123!",
        )
        salaries = self.client.get(
            reverse("salaries"),
            {"month": month_start.strftime("%Y-%m")},
        )
        self.assertEqual(salaries.status_code, 200)
        self.assertEqual(
            salaries.context["grand_total"],
            Decimal("600"),
        )

    def test_statistics_revenue_to_date_is_accumulated_for_selected_month(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        previous_month_end = current_month - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)

        Payment.objects.create(
            child=self.child,
            amount=Decimal("1000"),
            date=previous_month_start,
            created_by=self.admin,
        )
        Payment.objects.create(
            child=self.child,
            amount=Decimal("2000"),
            date=previous_month_end,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("statistics"),
            {"month": previous_month_start.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["revenue_to_date"],
            Decimal("3000"),
        )
        self.assertEqual(
            response.context["revenue_month"],
            Decimal("3000"),
        )

    def test_child_group_is_required_at_database_level(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Child.objects.create(
                    last_name="Безгруппный",
                    first_name="Иван",
                    birth_year=2015,
                    group=None,
                    status=Child.Status.ACTIVE,
                )

    def test_group_with_children_is_protected_from_delete(self):
        with self.assertRaises(ProtectedError):
            self.group.delete()

        self.assertTrue(
            Group.objects.filter(pk=self.group.pk).exists()
        )
        self.assertTrue(
            Child.objects.filter(pk=self.child.pk).exists()
        )

    def test_partial_prepayment_reduces_expected_renewal(self):
        today = timezone.localdate()
        next_month = (
            today.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_end = next_month - timedelta(days=1)

        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )

        Payment.objects.create(
            child=self.child,
            subscription=subscription,
            amount=Decimal("9000"),
            date=today,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("payments"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        row = next(
            item
            for item in response.context["rows"]
            if item["child"].pk == self.child.pk
        )

        self.assertEqual(
            row["prepaid_credit"],
            Decimal("3000"),
        )
        self.assertEqual(
            row["amount"],
            Decimal("3000"),
        )

    def test_full_prepayment_closes_call_and_forecast(self):
        today = timezone.localdate()
        next_month = (
            today.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_end = next_month - timedelta(days=1)

        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )

        Payment.objects.create(
            child=self.child,
            subscription=subscription,
            amount=Decimal("12000"),
            date=today,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        month = today.strftime("%Y-%m")
        prepayments = self.client.get(
            reverse("payments"),
            {"month": month},
        )
        statistics = self.client.get(
            reverse("statistics"),
            {"month": month},
        )

        self.assertEqual(prepayments.status_code, 200)
        self.assertEqual(statistics.status_code, 200)

        self.assertFalse(
            any(
                row["child"].pk == self.child.pk
                for row in prepayments.context["rows"]
            )
        )
        self.assertEqual(
            prepayments.context["expected"],
            Decimal("0"),
        )
        self.assertEqual(
            statistics.context["expected"],
            Decimal("0"),
        )

    def test_boss_dashboard_has_potential_revenue_and_full_trainer_kpi(self):
        today = timezone.localdate()
        next_month = (
            today.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_end = next_month - timedelta(days=1)

        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=month_end,
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )
        Payment.objects.create(
            child=self.child,
            subscription=subscription,
            amount=Decimal("1000"),
            date=today,
            created_by=self.admin,
        )

        Newcomer.objects.create(
            full_name="Пробник KPI",
            child=self.child,
            trial_at=timezone.now(),
            trainer=self.trainer,
            group=self.group,
            attended=True,
            paid=True,
        )

        competition = Competition.objects.create(
            name="Тест соревнований KPI",
            date=today,
            city="Москва",
        )
        CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="Общая",
        )

        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("boss"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["revenue"],
            Decimal("1000"),
        )
        self.assertEqual(
            response.context["expected_revenue"],
            Decimal("6000"),
        )
        self.assertEqual(
            response.context["potential_revenue"],
            Decimal("7000"),
        )

        trainer_row = next(
            row
            for row in response.context["trainer_rows"]
            if row["trainer"].pk == self.trainer.pk
        )
        self.assertEqual(trainer_row["trial"], 1)
        self.assertEqual(trainer_row["retained"], 1)
        self.assertEqual(trainer_row["retention_pct"], 100)

        self.assertEqual(
            response.context["top_trial_groups"][0]["name"],
            self.group.name,
        )
        self.assertEqual(
            response.context["top_competition_groups"][0]["name"],
            self.group.name,
        )

    def test_boss_competition_top_keeps_group_at_participation_after_transfer(self):
        today = timezone.localdate()

        other_trainer = Trainer.objects.create(
            full_name="Тренер новой группы",
        )
        other_group = Group.objects.create(
            name="Новая группа после перевода",
            trainer=other_trainer,
        )

        competition = Competition.objects.create(
            name="Историческое соревнование",
            date=today,
            city="Москва",
        )

        entry = CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="Общая",
        )

        self.assertEqual(
            entry.group_snapshot_id,
            self.group.pk,
        )

        self.child.group = other_group
        self.child.save(
            update_fields=["group"],
        )

        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("boss"),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        competition_groups = (
            response.context["top_competition_groups"]
        )

        self.assertEqual(
            competition_groups[0]["name"],
            self.group.name,
        )
        self.assertFalse(
            any(
                row["name"] == other_group.name
                for row in competition_groups
            )
        )

    def test_audit_middleware_records_unlogged_successful_actions(self):
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

        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            actor=self.admin,
            action="mark_attendance",
        ).first()

        self.assertIsNotNone(event)
        self.assertIn(
            "отметки посещения",
            event.description.lower(),
        )

    def test_explicit_audit_event_is_not_duplicated_by_middleware(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("payments"),
            {
                "action": "payment",
                "child_id": self.child.pk,
                "amount": "1500",
                "date": timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("payments"),
        )

        self.assertEqual(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="payment.create",
            ).count(),
            1,
        )

        self.assertFalse(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="payments.payment",
            ).exists()
        )

    def test_boss_can_export_full_audit_log_and_manager_cannot(self):
        AuditEvent.objects.create(
            actor=self.admin,
            action="test.action",
            description="Тестовое действие",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        self.assertEqual(
            self.client.get(
                reverse("boss_logs_export"),
            ).status_code,
            403,
        )

        self.client.logout()
        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("boss_logs_export"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_expired_subscription_with_debt_creates_notification(self):
        today = timezone.localdate()

        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=2),
            sessions_total=8,
            price=Decimal("6000"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("notifications"),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        notification = Notification.objects.get(
            recipient=self.admin,
            kind=Notification.Kind.SUBSCRIPTION_DEBT,
        )

        self.assertIn(
            "6000",
            notification.message,
        )

        self.assertIn(
            self.child.last_name,
            notification.message,
        )

        # Повторное открытие страницы не создаёт дубль.
        self.client.get(
            reverse("notifications"),
        )

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.admin,
                kind=Notification.Kind.SUBSCRIPTION_DEBT,
            ).count(),
            1,
        )
        
    def test_admin_can_confirm_today_trial_from_notifications(self):
        today = timezone.localdate()

        trial_at = timezone.make_aware(
            datetime.combine(
                today,
                time(18, 0),
            )
        )

        newcomer = Newcomer.objects.create(
            full_name="Петрова Алиса",
            trial_at=trial_at,
            trainer=self.trainer,
            group=self.group,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("notifications"),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "Петрова Алиса",
        )

        response = self.client.post(
            reverse("notifications"),
            {
                "action": "confirm_trial",
                "newcomer_id": newcomer.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("notifications"),
        )

        newcomer.refresh_from_db()

        self.assertTrue(
            newcomer.attended,
        )

        response = self.client.get(
            reverse("notifications"),
        )

        self.assertNotContains(
            response,
            "Подтвердите приход спортсменов",
        )

    def test_attendance_trial_modal_creates_child_and_newcomer_with_schedule(self):
        self.client.login(username="admin", password="TestPass123!")
        trial_date = timezone.localdate() + timedelta(days=2)

        page = self.client.get(
            reverse("attendance"),
            {"group_id": self.group.pk},
        )
        self.assertContains(page, 'name="birth_date"')
        self.assertContains(page, 'name="age"')
        self.assertContains(page, 'name="trial_date"')
        self.assertContains(page, 'name="trial_time"')
        self.assertContains(page, 'name="comment"')
        self.assertContains(page, "Без оплаты через 1 месяц")
        self.assertContains(page, self.trainer.full_name)
        self.assertContains(page, self.group.name)

        response = self.client.post(
            reverse("add_trial_child", args=[self.group.pk]),
            {
                "last_name": "Петрова",
                "first_name": "Алиса",
                "patronymic": "Игоревна",
                "birth_date": "2017-04-12",
                "age": "",
                "parent_phone": "+79990000000",
                "trial_date": trial_date.isoformat(),
                "trial_time": "18:30",
                "comment": "Первое пробное",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('attendance')}?group_id={self.group.pk}",
        )

        child = Child.objects.get(
            last_name="Петрова",
            first_name="Алиса",
        )
        newcomer = Newcomer.objects.get(child=child)

        self.assertEqual(child.status, Child.Status.TRIAL)
        self.assertEqual(child.group, self.group)
        self.assertEqual(child.birth_date, datetime(2017, 4, 12).date())
        self.assertEqual(child.birth_year, 2017)
        self.assertEqual(child.trial_from, trial_date)
        self.assertEqual(child.parent_phone, "+79990000000")
        self.assertEqual(child.note, "Первое пробное")

        self.assertEqual(newcomer.group, self.group)
        self.assertEqual(newcomer.trainer, self.trainer)
        self.assertEqual(newcomer.phone, "+79990000000")
        self.assertEqual(newcomer.comment, "Первое пробное")

        local_trial = timezone.localtime(newcomer.trial_at)
        self.assertEqual(local_trial.date(), trial_date)
        self.assertEqual(
            (local_trial.hour, local_trial.minute),
            (18, 30),
        )

    def test_trial_expires_only_after_one_month_without_payment(self):
        today = timezone.localdate()
        trial = Child.objects.create(
            last_name="Месячная",
            first_name="Проба",
            birth_year=2016,
            group=self.group,
            status=Child.Status.TRIAL,
            trial_from=today - timedelta(days=29),
        )

        self.assertFalse(trial.is_trial_expired())
        self.assertEqual(expire_trials(today=today), 0)

        trial.refresh_from_db()
        self.assertEqual(trial.status, Child.Status.TRIAL)

        trial.trial_from = today - timedelta(days=30)
        trial.save(update_fields=["trial_from"])

        self.assertTrue(trial.is_trial_expired())
        self.assertEqual(expire_trials(today=today), 1)

        trial.refresh_from_db()
        self.assertEqual(trial.status, Child.Status.LOST)
        self.assertEqual(trial.departure_group, self.group)
        self.assertEqual(trial.departure_trainer, self.trainer)

    def test_attendance_header_counts_present_children_for_group_and_club(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        other_trainer = Trainer.objects.create(
            full_name="Другой тренер",
        )
        other_group = Group.objects.create(
            name="Другая группа",
            trainer=other_trainer,
        )
        other_slot = ScheduleSlot.objects.create(
            group=other_group,
            weekday=today.weekday(),
            start_time=time(19, 0),
        )
        moved_child = Child.objects.create(
            last_name="Переведённая",
            first_name="Мария",
            birth_year=2016,
            group=other_group,
        )
        other_child = Child.objects.create(
            last_name="Другая",
            first_name="Анна",
            birth_year=2015,
            group=other_group,
        )
        absent_child = Child.objects.create(
            last_name="Пропуск",
            first_name="Ольга",
            birth_year=2015,
            group=self.group,
        )

        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )
        Attendance.objects.create(
            child=moved_child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )
        Attendance.objects.create(
            child=other_child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=other_group,
            trainer_snapshot=other_trainer,
        )
        Attendance.objects.create(
            child=other_child,
            date=today,
            slot=other_slot,
            status=Attendance.Status.PRESENT,
            group_snapshot=other_group,
            trainer_snapshot=other_trainer,
        )
        Attendance.objects.create(
            child=absent_child,
            date=today,
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )

        self.client.login(username="admin", password="TestPass123!")
        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["week_data"]), 1)
        entry = response.context["week_data"][0]
        self.assertEqual(entry["group_present_count"], 2)
        self.assertEqual(entry["total_present_count"], 3)
        self.assertContains(
            response,
            f'data-attendance-counter-date="{today.isoformat()}"',
        )
        self.assertContains(
            response,
            'data-group-present-count>2</span>',
        )
        self.assertContains(
            response,
            'data-total-present-count>3</span>',
        )
        self.assertContains(
            response,
            "updatePresentCounters",
        )

    def test_attendance_grid_is_dense_and_uses_dynamic_equal_columns(self):
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=timezone.localdate().weekday(),
            start_time=time(18, 0),
        )
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.get(
            reverse("attendance"),
            {"group_id": self.group.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="data-table attendance-grid"',
        )
        self.assertContains(
            response,
            f'style="--attendance-days: {len(response.context["week_data"])};"',
        )
        self.assertContains(response, "attendance-person-cell")
        self.assertContains(response, "attendance-date-cell")
        self.assertContains(response, "attendance-mark-cell")
        self.assertNotContains(
            response,
            'class="data-table min-w-[1280px]"',
        )
        self.assertNotContains(
            response,
            'style="width:44px;height:44px"',
        )

    def test_move_class_to_any_free_day_updates_calendar_and_ui(self):
        source_date = timezone.localdate() + timedelta(days=14)
        replacement_date = source_date + timedelta(days=2)
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=source_date.weekday(),
            start_time=time(18, 0),
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": source_date.isoformat(),
                "replacement_date": replacement_date.isoformat(),
                "replacement_time": "19:30",
            },
        )

        self.assertEqual(response.status_code, 302)
        override = ScheduleOverride.objects.get(group=self.group)
        self.assertEqual(override.original_date, source_date)
        self.assertEqual(override.replacement_date, replacement_date)
        self.assertEqual(
            (override.replacement_start_time.hour, override.replacement_start_time.minute),
            (19, 30),
        )
        self.assertEqual(
            effective_class_dates(
                self.group,
                source_date,
                replacement_date,
            ),
            [replacement_date],
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="schedule.move",
                object_id=str(override.pk),
            ).exists()
        )

        page = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "custom",
                "date_from": source_date.isoformat(),
                "date_to": replacement_date.isoformat(),
                "ref_date": replacement_date.isoformat(),
            },
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(
            [entry["date"] for entry in page.context["week_data"]],
            [replacement_date],
        )
        entry = page.context["week_data"][0]
        self.assertTrue(entry["is_moved"])
        self.assertEqual(entry["moved_from"], source_date)
        self.assertEqual(
            (entry["start_time"].hour, entry["start_time"].minute),
            (19, 30),
        )
        self.assertContains(page, "Перенести занятие")
        self.assertContains(page, 'name="replacement_date"')
        self.assertContains(page, 'name="replacement_time"')
        self.assertContains(page, 'name="extend_subscriptions"')
        self.assertContains(page, f"↪ с {source_date:%d.%m}")

    def test_moved_class_can_be_moved_again(self):
        source_date = timezone.localdate() + timedelta(days=14)
        first_target = source_date + timedelta(days=1)
        second_target = source_date + timedelta(days=2)
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=source_date.weekday(),
            start_time=time(18, 0),
        )
        self.client.login(username="admin", password="TestPass123!")

        first = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": source_date.isoformat(),
                "replacement_date": first_target.isoformat(),
                "replacement_time": "18:45",
            },
        )
        self.assertEqual(first.status_code, 302)

        second = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": first_target.isoformat(),
                "replacement_date": second_target.isoformat(),
                "replacement_time": "",
            },
        )
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            ScheduleOverride.objects.filter(group=self.group).count(),
            2,
        )
        self.assertEqual(
            effective_class_dates(
                self.group,
                source_date,
                second_target,
            ),
            [second_target],
        )
        latest = ScheduleOverride.objects.get(
            group=self.group,
            original_date=first_target,
        )
        self.assertEqual(
            (latest.replacement_start_time.hour, latest.replacement_start_time.minute),
            (18, 45),
        )

    def test_move_class_rejects_conflict_and_existing_marks(self):
        source_date = timezone.localdate() + timedelta(days=14)
        occupied_date = source_date + timedelta(days=1)
        free_date = source_date + timedelta(days=2)
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=source_date.weekday(),
            start_time=time(18, 0),
        )
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=occupied_date.weekday(),
            start_time=time(19, 0),
        )
        self.client.login(username="admin", password="TestPass123!")

        conflict = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": source_date.isoformat(),
                "replacement_date": occupied_date.isoformat(),
                "replacement_time": "20:00",
            },
        )
        self.assertEqual(conflict.status_code, 302)
        self.assertFalse(
            ScheduleOverride.objects.filter(group=self.group).exists()
        )

        Attendance.objects.create(
            child=self.child,
            date=source_date,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )
        marked = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": source_date.isoformat(),
                "replacement_date": free_date.isoformat(),
                "replacement_time": "20:00",
            },
        )
        self.assertEqual(marked.status_code, 302)
        self.assertFalse(
            ScheduleOverride.objects.filter(group=self.group).exists()
        )

    def test_move_class_optionally_extends_active_subscriptions(self):
        source_date = timezone.localdate() + timedelta(days=14)
        replacement_date = source_date + timedelta(days=3)
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=source_date.weekday(),
            start_time=time(18, 0),
        )
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=source_date - timedelta(days=10),
            end_date=source_date + timedelta(days=20),
            sessions_total=8,
            price=Decimal("5000"),
        )
        original_end = subscription.end_date
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("move_class"),
            {
                "group_id": self.group.pk,
                "original_date": source_date.isoformat(),
                "replacement_date": replacement_date.isoformat(),
                "replacement_time": "18:00",
                "extend_subscriptions": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        subscription.refresh_from_db()
        self.assertEqual(
            subscription.end_date,
            original_end + timedelta(days=3),
        )
        override = ScheduleOverride.objects.get(group=self.group)
        self.assertTrue(override.extend_subscriptions)
        self.assertEqual(override.extension_days, 3)

    def test_attendance_period_presets_use_real_class_dates(self):
        reference = timezone.localdate().replace(day=15)
        month_start = reference.replace(day=1)
        month_end = (
            month_start.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1) - timedelta(days=1)
        previous_month = (
            month_start - timedelta(days=1)
        ).replace(day=1)
        quarter_start = (
            previous_month - timedelta(days=1)
        ).replace(day=1)

        for weekday in (0, 2):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )

        self.client.login(username="admin", password="TestPass123!")
        cases = {
            "day": (reference, reference),
            "month": (month_start, month_end),
            "quarter": (quarter_start, month_end),
            "year": (
                reference.replace(month=1, day=1),
                reference.replace(month=12, day=31),
            ),
        }

        for period, (start, end) in cases.items():
            with self.subTest(period=period):
                response = self.client.get(
                    reverse("attendance"),
                    {
                        "group_id": self.group.pk,
                        "period": period,
                        "ref_date": reference.isoformat(),
                    },
                )
                expected = [
                    start + timedelta(days=offset)
                    for offset in range((end - start).days + 1)
                    if (start + timedelta(days=offset)).weekday() in {0, 2}
                ]
                self.assertEqual(
                    [item["date"] for item in response.context["week_data"]],
                    expected,
                )
                self.assertEqual(response.context["period_start"], start)
                self.assertEqual(response.context["period_end"], end)
                self.assertIn(f"period={period}", response.context["filter_query"])

    def test_attendance_custom_period_normalizes_and_empty_day_is_valid(self):
        today = timezone.localdate()
        early = today - timedelta(days=8)
        late = today + timedelta(days=3)
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=early.weekday(),
            start_time=time(18, 0),
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "custom",
                "ref_date": today.isoformat(),
                "date_from": late.isoformat(),
                "date_to": early.isoformat(),
            },
        )
        self.assertEqual(response.context["period_start"], early)
        self.assertEqual(response.context["period_end"], late)
        self.assertEqual(response.context["date_from"], early)
        self.assertEqual(response.context["date_to"], late)
        self.assertIn(f"date_from={early.isoformat()}", response.context["filter_query"])
        self.assertIn(f"date_to={late.isoformat()}", response.context["filter_query"])

        no_class_day = next(
            today + timedelta(days=offset)
            for offset in range(7)
            if (today + timedelta(days=offset)).weekday() != early.weekday()
        )
        empty = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": no_class_day.isoformat(),
            },
        )
        self.assertEqual(empty.context["week_data"], [])
        self.assertIsNone(empty.context.get("error"))
        self.assertContains(empty, "В выбранном периоде занятий нет.")

    def _create_daily_schedule(self):
        for weekday in range(7):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )

    def _attendance_child_row(self, response):
        return next(
            row
            for row in response.context["children_data"]
            if row["child"].pk == self.child.pk
        )

    def test_subscription_end_marker_uses_projected_date_and_shifts_for_excused(self):
        today = timezone.localdate()
        self._create_daily_schedule()
        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=30),
            sessions_total=3,
            price=Decimal("3000"),
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=2),
            status=Attendance.Status.PRESENT,
        )
        movable_mark = Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=1),
            status=Attendance.Status.EXCUSED,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {"group_id": self.group.pk},
        )
        row = self._attendance_child_row(response)
        expected_with_excused = today + timedelta(days=1)

        self.assertEqual(
            row["subscription_end"],
            expected_with_excused,
        )
        self.assertTrue(
            row["subscription_ending_soon"],
        )
        self.assertEqual(
            response.context["week_data"][row["subscription_end_index"]]["date"],
            expected_with_excused,
        )
        self.assertContains(
            response,
            f"до {expected_with_excused:%d.%m}",
        )
        self.assertContains(
            response,
            "border-r-2 border-red-500",
        )

        movable_mark.status = Attendance.Status.ABSENT
        movable_mark.save(update_fields=["status"])

        response = self.client.get(
            reverse("attendance"),
            {"group_id": self.group.pk},
        )
        row = self._attendance_child_row(response)

        self.assertEqual(
            row["subscription_end"],
            today,
        )
        self.assertEqual(
            response.context["week_data"][row["subscription_end_index"]]["date"],
            today,
        )
        self.assertContains(
            response,
            f"до {today:%d.%m}",
        )

    def test_subscription_end_marker_handles_hidden_non_class_date(self):
        today = timezone.localdate()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7

        monday = today + timedelta(days=days_until_monday)
        hidden_end = monday + timedelta(days=1)
        wednesday = monday + timedelta(days=2)

        for weekday in (monday.weekday(), wednesday.weekday()):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )

        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=hidden_end,
            sessions_total=20,
            price=Decimal("6000"),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": hidden_end.isoformat(),
            },
        )
        row = self._attendance_child_row(response)
        visible_dates = [
            item["date"]
            for item in response.context["week_data"]
        ]

        self.assertNotIn(hidden_end, visible_dates)
        self.assertEqual(row["subscription_end"], hidden_end)
        self.assertIsNotNone(row["subscription_end_index"])
        self.assertEqual(
            visible_dates[row["subscription_end_index"]],
            monday,
        )
        self.assertGreater(
            visible_dates[row["subscription_end_index"] + 1],
            hidden_end,
        )
        self.assertContains(
            response,
            "border-r-2 border-red-500",
        )

    def test_subscription_end_marker_is_shown_even_earlier_than_seven_days(self):
        today = timezone.localdate()
        self._create_daily_schedule()
        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=60),
            sessions_total=20,
            price=Decimal("6000"),
        )
        projected_end = today + timedelta(days=19)

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": projected_end.isoformat(),
            },
        )
        row = self._attendance_child_row(response)

        self.assertEqual(
            row["subscription_end"],
            projected_end,
        )
        self.assertFalse(
            row["subscription_ending_soon"],
        )
        self.assertEqual(
            response.context["week_data"][row["subscription_end_index"]]["date"],
            projected_end,
        )
        self.assertContains(
            response,
            f"до {projected_end:%d.%m}",
        )
        self.assertContains(
            response,
            "border-r-2 border-red-500",
        )

    def test_subscription_end_marker_stays_on_today_when_sessions_are_exhausted(self):
        today = timezone.localdate()
        self._create_daily_schedule()
        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=1,
            price=Decimal("3000"),
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "ref_date": today.isoformat(),
            },
        )
        row = self._attendance_child_row(response)

        self.assertEqual(row["sessions_left"], 0)
        self.assertEqual(row["subscription_end"], today)
        self.assertTrue(row["subscription_ending_soon"])
        self.assertEqual(
            response.context["week_data"][row["subscription_end_index"]]["date"],
            today,
        )
        self.assertContains(
            response,
            "border-r-2 border-red-500",
        )
