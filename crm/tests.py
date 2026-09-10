from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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
    AttendanceReason,
    AuditEvent,
    Child,
    ChildGroupMembership,
    Competition,
    CompetitionDocument,
    CompetitionEntry,
    Expense,
    Group,
    Lead,
    LessonTrainerAssignment,
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

    def test_child_card_compacts_header_and_shows_history_context(self):
        today = timezone.localdate()
        slot = ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 30),
        )
        self.child.discount_percent = 15
        self.child.note = "Позвонить родителю после занятия"
        self.child.save(update_fields=["discount_percent", "note"])
        Attendance.objects.create(
            child=self.child,
            date=today,
            slot=slot,
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-child-status-indicators")
        self.assertContains(response, 'data-child-indicator="debt"')
        self.assertContains(response, 'data-child-indicator="discount"')
        self.assertContains(response, 'data-child-indicator="documents"')
        self.assertContains(response, "Скидка")
        self.assertContains(response, "15%")
        self.assertNotContains(response, ">Осталось<")
        self.assertNotContains(response, ">Пропуски<")
        self.assertContains(response, "data-finance-summary")
        self.assertContains(response, 'data-finance-balance="zero"')
        self.assertContains(response, "Баланс")
        self.assertNotContains(response, "Ближайшее окончание")
        self.assertNotIn("sessions_left", response.context)
        self.assertNotIn("balance", response.context)
        self.assertNotIn("missed_percent", response.context)
        self.assertNotIn("nearest_expiry", response.context)

        self.assertContains(response, "data-attendance-history-meta")
        self.assertContains(response, self.group.name)
        self.assertContains(response, self.trainer.full_name)
        self.assertContains(response, "18:30")

        html = response.content.decode()
        self.assertLess(
            html.index("Позвонить родителю после занятия"),
            html.index("data-child-attendance-period"),
        )

    def test_child_financial_summary_uses_one_source_for_balance(self):
        today = timezone.localdate()
        active_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        cancelled_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=30),
            sessions_total=8,
            price=Decimal("9000"),
            is_active=False,
            cancelled_at=timezone.now(),
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            charge_amount=Decimal("750"),
        )
        payment = Payment.objects.create(
            child=self.child,
            subscription=active_subscription,
            amount=Decimal("7000"),
            date=today,
            created_by=self.admin,
        )

        summary = self.child.financial_summary()
        self.assertEqual(summary["paid"], Decimal("7000"))
        self.assertEqual(summary["subscription_charges"], Decimal("5000"))
        self.assertEqual(summary["attendance_charges"], Decimal("750"))
        self.assertEqual(summary["charged"], Decimal("5750"))
        self.assertEqual(summary["balance"], Decimal("1250"))
        self.assertEqual(summary["credit"], Decimal("1250"))
        self.assertEqual(summary["debt"], Decimal("0"))
        self.assertEqual(summary["balance_state"], "credit")
        self.assertEqual(self.child.balance(), Decimal("1250"))
        self.assertEqual(self.child.debt(), Decimal("0"))

        movements = self.child.financial_movements()
        self.assertEqual(len(movements), 5)
        self.assertEqual(
            sum(
                (movement["amount"] for movement in movements),
                Decimal("0"),
            ),
            summary["balance"],
        )
        amounts_by_kind = {}
        for movement in movements:
            amounts_by_kind.setdefault(
                movement["kind"],
                [],
            ).append(movement["amount"])
        self.assertCountEqual(
            amounts_by_kind["subscription"],
            [Decimal("-5000"), Decimal("-9000")],
        )
        self.assertEqual(
            amounts_by_kind["subscription_cancel"],
            [Decimal("9000")],
        )
        self.assertEqual(
            amounts_by_kind["attendance_charge"],
            [Decimal("-750")],
        )
        self.assertEqual(
            amounts_by_kind["payment"],
            [Decimal("7000")],
        )
        cancel_movement = next(
            movement
            for movement in movements
            if (
                movement["kind"] == "subscription_cancel"
                and movement["object_id"] == cancelled_subscription.pk
            )
        )
        self.assertEqual(cancel_movement["direction"], "credit")

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-finance-summary")
        self.assertContains(response, 'data-finance-balance="credit"')
        self.assertContains(response, "+1250 ₽")
        self.assertContains(response, "Начислено")
        self.assertContains(response, "Разовые / долг: 750 ₽")
        self.assertContains(response, "data-finance-journal")
        self.assertContains(
            response,
            'data-finance-kind="subscription"',
            count=2,
        )
        self.assertContains(
            response,
            'data-finance-kind="subscription_cancel"',
            count=1,
        )
        self.assertContains(
            response,
            'data-finance-kind="attendance_charge"',
            count=1,
        )
        self.assertContains(
            response,
            'data-finance-kind="payment"',
            count=1,
        )
        self.assertContains(response, "История списаний и оплат")
        self.assertContains(response, "Начислен абонемент")
        self.assertContains(response, "Отмена абонемента")
        self.assertContains(response, "Занятие в долг")

        payment.amount = Decimal("4000")
        payment.save(update_fields=["amount"])
        self.child.refresh_from_db()

        summary = self.child.financial_summary()
        self.assertEqual(summary["balance"], Decimal("-1750"))
        self.assertEqual(summary["credit"], Decimal("0"))
        self.assertEqual(summary["debt"], Decimal("1750"))
        self.assertEqual(summary["balance_state"], "debt")
        self.assertEqual(self.child.debt(), Decimal("1750"))
        self.assertEqual(
            sum(
                (
                    movement["amount"]
                    for movement in self.child.financial_movements()
                ),
                Decimal("0"),
            ),
            summary["balance"],
        )

    def test_child_card_shows_trial_history_after_payment(self):
        trial_at = (
            timezone.now()
            - timedelta(days=2)
        ).replace(second=0, microsecond=0)
        self.child.status = Child.Status.TRIAL
        self.child.trial_from = timezone.localdate(trial_at)
        self.child.save(update_fields=["status", "trial_from"])
        newcomer = Newcomer.objects.create(
            full_name="Иванова Анна",
            child=self.child,
            trial_at=trial_at,
            trainer=self.trainer,
            group=self.group,
            attended=True,
            source="VK",
            comment="Первое пробное в основной группе",
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        before_payment = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(before_payment.status_code, 200)
        self.assertContains(before_payment, "data-child-trial")
        self.assertContains(
            before_payment,
            'data-trial-state="attended"',
        )
        self.assertContains(
            before_payment,
            'data-trial-payment="unpaid"',
        )
        self.assertContains(before_payment, "Пробное")
        self.assertContains(before_payment, "Был на пробном")
        self.assertContains(before_payment, "Без оплаты")
        self.assertContains(before_payment, self.group.name)
        self.assertContains(before_payment, self.trainer.full_name)
        self.assertContains(before_payment, "VK")
        self.assertContains(
            before_payment,
            "Первое пробное в основной группе",
        )
        self.assertContains(
            before_payment,
            timezone.localtime(trial_at).strftime("%d.%m.%Y %H:%M"),
        )

        Payment.objects.create(
            child=self.child,
            amount=Decimal("1500"),
            date=timezone.localdate(),
            created_by=self.admin,
        )
        self.child.refresh_from_db()
        newcomer.refresh_from_db()

        self.assertEqual(self.child.status, Child.Status.ACTIVE)
        self.assertTrue(newcomer.paid)

        after_payment = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertContains(after_payment, "data-child-trial")
        self.assertContains(
            after_payment,
            'data-trial-payment="paid"',
        )
        self.assertContains(after_payment, "Оплачено")

    def test_child_card_supports_two_parent_contacts_and_dispensary_region(self):
        self.child.parent_name = "Иванова Ольга"
        self.child.parent_phone = "+79990000001"
        self.child.second_parent_name = "Иванов Сергей"
        self.child.second_parent_phone = "+79990000002"
        self.child.dispensary_region = Child.DispensaryRegion.MOSCOW_REGION
        self.child.save(update_fields=[
            "parent_name",
            "parent_phone",
            "second_parent_name",
            "second_parent_phone",
            "dispensary_region",
        ])

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-child-contacts')
        self.assertContains(response, 'data-parent-contact="primary"')
        self.assertContains(response, 'data-parent-contact="secondary"')
        self.assertContains(response, "Иванова Ольга")
        self.assertContains(response, "Иванов Сергей")
        self.assertContains(response, 'href="tel:+79990000001"')
        self.assertContains(response, 'href="tel:+79990000002"')
        self.assertContains(response, "Прикрепление для диспансеризации")
        self.assertContains(response, "Московская область")

        form = response.context["child_form"]
        self.assertIn("second_parent_name", form.fields)
        self.assertIn("second_parent_phone", form.fields)
        self.assertIn("dispensary_region", form.fields)

    def test_child_edit_saves_second_parent_and_dispensary_region(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_edit", args=[self.child.pk]),
            {
                "last_name": self.child.last_name,
                "first_name": self.child.first_name,
                "patronymic": "",
                "birth_date": "",
                "birth_year": str(self.child.birth_year),
                "parent_name": "Иванова Ольга",
                "parent_phone": "+79990000001",
                "second_parent_name": "Иванов Сергей",
                "second_parent_phone": "+79990000002",
                "address": "Москва, ул. Спортивная, 1",
                "dispensary_region": Child.DispensaryRegion.MOSCOW,
                "certificate_note": "",
                "group": str(self.group.pk),
                "status": Child.Status.ACTIVE,
                "trial_from": "",
                "discount_percent": "0",
                "note": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_name, "Иванова Ольга")
        self.assertEqual(self.child.parent_phone, "+79990000001")
        self.assertEqual(self.child.second_parent_name, "Иванов Сергей")
        self.assertEqual(self.child.second_parent_phone, "+79990000002")
        self.assertEqual(
            self.child.dispensary_region,
            Child.DispensaryRegion.MOSCOW,
        )

    def test_invalid_child_edit_does_not_freeze_attendance_history(self):
        mark = Attendance.objects.create(
            child=self.child,
            date=timezone.localdate() - timedelta(days=1),
            status=Attendance.Status.ABSENT,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("child_edit", args=[self.child.pk]),
            {
                "last_name": self.child.last_name,
                "first_name": "",
                "patronymic": "",
                "birth_date": "",
                "birth_year": str(self.child.birth_year),
                "parent_name": "",
                "parent_phone": "",
                "second_parent_name": "",
                "second_parent_phone": "",
                "address": "",
                "dispensary_region": "",
                "certificate_note": "",
                "group": str(self.group.pk),
                "status": Child.Status.ACTIVE,
                "trial_from": "",
                "discount_percent": "0",
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        mark.refresh_from_db()
        self.assertIsNone(mark.group_snapshot_id)
        self.assertIsNone(mark.trainer_snapshot_id)
        self.assertIsNone(mark.salary_rate_snapshot)

    def test_child_edit_group_change_archives_old_primary_membership(self):
        second_group = Group.objects.create(
            name="Группа после перевода",
            trainer=self.trainer,
        )
        old_membership = self.child.group_memberships.get(group=self.group)
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("child_edit", args=[self.child.pk]),
            {
                "last_name": self.child.last_name,
                "first_name": self.child.first_name,
                "patronymic": "",
                "birth_date": "",
                "birth_year": str(self.child.birth_year),
                "parent_name": "",
                "parent_phone": "",
                "second_parent_name": "",
                "second_parent_phone": "",
                "address": "",
                "dispensary_region": "",
                "certificate_note": "",
                "group": str(second_group.pk),
                "status": Child.Status.ACTIVE,
                "trial_from": "",
                "discount_percent": "0",
                "note": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        old_membership.refresh_from_db()
        new_membership = self.child.group_memberships.get(group=second_group)
        self.assertEqual(self.child.group, second_group)
        self.assertFalse(old_membership.is_primary)
        self.assertIsNotNone(old_membership.archived_at)
        self.assertTrue(new_membership.is_primary)
        self.assertIsNone(new_membership.archived_at)

    def test_child_save_creates_primary_group_membership(self):
        membership = ChildGroupMembership.objects.get(
            child=self.child,
            group=self.group,
        )
        self.assertTrue(membership.is_primary)
        self.assertIsNone(membership.archived_at)

    def test_child_card_repairs_primary_membership_for_legacy_child(self):
        self.child.group_memberships.all().delete()
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        membership = ChildGroupMembership.objects.get(
            child=self.child,
            group=self.group,
        )
        self.assertTrue(membership.is_primary)
        self.assertIsNone(membership.archived_at)
        self.assertContains(response, "data-group-memberships")
        self.assertContains(
            response,
            f'data-group-membership="{membership.pk}"',
        )
        self.assertContains(response, "Основная")

    def test_child_can_have_multiple_groups_and_change_primary(self):
        substitute_trainer = Trainer.objects.create(
            full_name="Тренер хореографии",
        )
        second_group = Group.objects.create(
            name="Хореография",
            trainer=substitute_trainer,
        )
        mark = Attendance.objects.create(
            child=self.child,
            date=timezone.localdate(),
            status=Attendance.Status.ABSENT,
        )
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "add_group_membership",
                "group_id": second_group.pk,
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )

        primary = ChildGroupMembership.objects.get(
            child=self.child,
            group=self.group,
        )
        additional = ChildGroupMembership.objects.get(
            child=self.child,
            group=second_group,
        )
        self.assertTrue(primary.is_primary)
        self.assertFalse(additional.is_primary)
        self.assertFalse(additional.requires_subscription)

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "set_primary_group",
                "membership_id": additional.pk,
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )

        self.child.refresh_from_db()
        primary.refresh_from_db()
        additional.refresh_from_db()
        mark.refresh_from_db()
        self.assertEqual(self.child.group, second_group)
        self.assertFalse(primary.is_primary)
        self.assertIsNone(primary.archived_at)
        self.assertTrue(additional.is_primary)
        self.assertEqual(mark.group_snapshot, self.group)
        self.assertEqual(mark.trainer_snapshot, self.trainer)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="child.group_membership.primary",
                object_id=str(self.child.pk),
            ).exists()
        )

    def test_child_card_shows_subscription_state_and_groups_primary_trainer_first(self):
        today = timezone.localdate()
        other_trainer = Trainer.objects.create(
            full_name="Другой тренер карточки",
        )
        paid_without_subscription = Group.objects.create(
            name="Платная группа без абонемента",
            trainer=other_trainer,
        )
        personal_group = Group.objects.create(
            name="Персональная группа",
            trainer=other_trainer,
        )
        primary_available = Group.objects.create(
            name="Свободная группа основного тренера",
            trainer=self.trainer,
        )
        other_available = Group.objects.create(
            name="Свободная группа другого тренера",
            trainer=other_trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=paid_without_subscription,
            requires_subscription=True,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=personal_group,
            requires_subscription=False,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        rendered_memberships = {
            membership.group_id: membership
            for membership in response.context["memberships"]
        }
        self.assertTrue(
            rendered_memberships[self.group.pk].has_active_subscription,
        )
        self.assertFalse(
            rendered_memberships[
                paid_without_subscription.pk
            ].has_active_subscription,
        )
        self.assertFalse(
            rendered_memberships[personal_group.pk].has_active_subscription,
        )
        self.assertContains(
            response,
            'data-membership-subscription-state="active"',
            count=1,
        )
        self.assertContains(
            response,
            'data-membership-subscription-state="missing"',
            count=1,
        )
        self.assertContains(
            response,
            'data-membership-subscription-state="not-required"',
            count=1,
        )
        self.assertContains(response, "Активный абонемент")
        self.assertContains(response, "Нет активного абонемента")
        self.assertContains(response, "Абонемент не требуется")
        self.assertContains(response, "data-primary-trainer-groups")
        self.assertContains(response, "data-other-trainer-groups")
        self.assertContains(response, primary_available.name)
        self.assertContains(response, other_available.name)

        html = response.content.decode()
        self.assertLess(
            html.index("data-primary-trainer-groups"),
            html.index("data-other-trainer-groups"),
        )

        membership_count = self.child.group_memberships.count()
        invalid = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {"action": "add_group_membership"},
        )
        self.assertRedirects(
            invalid,
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(
            self.child.group_memberships.count(),
            membership_count,
        )

    def test_group_subscription_tariffs_keep_subscription_and_debt_prices_separate(self):
        from .forms import GroupForm

        main_tariff = Tariff.objects.create(
            name="Основной абонемент",
            price=Decimal("5000"),
            sessions_total=8,
            duration_days=30,
        )
        extended_tariff = Tariff.objects.create(
            name="Расширенный абонемент",
            price=Decimal("8500"),
            sessions_total=16,
            duration_days=60,
        )
        inactive_tariff = Tariff.objects.create(
            name="Архивный абонемент",
            price=Decimal("4500"),
            sessions_total=8,
            duration_days=30,
            is_active=False,
        )

        form = GroupForm(
            data={
                "name": self.group.name,
                "trainer": self.trainer.pk,
                "capacity": "",
                "subscription_tariffs": [main_tariff.pk, extended_tariff.pk],
                "single_session_price": "1500",
                "is_active": "on",
            },
            instance=self.group,
        )
        self.assertTrue(form.is_valid(), form.errors.as_text())
        group = form.save()

        self.assertEqual(
            set(group.subscription_tariffs.values_list("pk", flat=True)),
            {main_tariff.pk, extended_tariff.pk},
        )
        self.assertEqual(group.single_session_price, Decimal("1500"))
        self.assertEqual(main_tariff.price, Decimal("5000"))

        group.subscription_tariffs.add(inactive_tariff)
        edit_form = GroupForm(instance=group)
        self.assertIn(
            inactive_tariff.pk,
            edit_form.fields["subscription_tariffs"].queryset.values_list(
                "pk", flat=True,
            ),
        )

        self.client.login(username="admin", password="TestPass123!")
        response = self.client.get(reverse("group_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Стоимость")
        self.assertContains(response, "Основной абонемент")
        self.assertContains(response, "5000 ₽")
        self.assertContains(response, "Разовое / долг: 1500 ₽")
        rendered_group = next(
            item for item in response.context["groups"]
            if item.pk == group.pk
        )
        self.assertIn(
            "subscription_tariffs",
            rendered_group._prefetched_objects_cache,
        )

    def test_unslotted_attendance_is_unique_per_child_group_and_day(self):
        today = timezone.localdate()
        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(
                    child=self.child,
                    date=today,
                    status=Attendance.Status.ABSENT,
                    group_snapshot=self.group,
                    trainer_snapshot=self.trainer,
                )

        second_group = Group.objects.create(
            name="Параллельная группа",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=second_group,
            trainer_snapshot=self.trainer,
        )

        self.assertEqual(
            Attendance.objects.filter(
                child=self.child,
                date=today,
            ).count(),
            2,
        )

    def test_additional_group_attendance_is_group_scoped(self):
        today = timezone.localdate()
        second_trainer = Trainer.objects.create(full_name="Тренер второй группы")
        second_group = Group.objects.create(
            name="Вторая группа",
            trainer=second_trainer,
        )
        replacement = Trainer.objects.create(full_name="Тренер замены")
        for target_group in (self.group, second_group):
            ScheduleSlot.objects.create(
                group=target_group,
                weekday=today.weekday(),
                start_time=time(18, 0),
            )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=second_group,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("6000"),
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.get(
            reverse("attendance"),
            {"group_id": second_group.pk, "period": "day", "ref_date": today.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            self.child.pk,
            [row["child"].pk for row in response.context["children_data"]],
        )

        second_response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": second_group.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )
        self.assertEqual(second_response.status_code, 200)
        second_mark = Attendance.objects.get(
            child=self.child,
            date=today,
            group_snapshot=second_group,
        )
        self.assertEqual(second_mark.trainer_snapshot, second_trainer)

        primary_response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": self.group.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.ABSENT,
            },
        )
        self.assertEqual(primary_response.status_code, 200)
        self.assertEqual(
            Attendance.objects.filter(child=self.child, date=today).count(),
            2,
        )

        assign_response = self.client.post(
            reverse("assign_lesson_trainer"),
            {
                "group_id": second_group.pk,
                "lesson_date": today.isoformat(),
                "trainer_id": replacement.pk,
                "child_ids": [str(self.child.pk)],
            },
        )
        self.assertEqual(assign_response.status_code, 302)
        second_mark.refresh_from_db()
        self.assertEqual(second_mark.trainer_snapshot, replacement)

        cancel_response = self.client.post(
            reverse("cancel_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": second_group.pk,
                "date": today.isoformat(),
            },
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertFalse(
            Attendance.objects.filter(pk=second_mark.pk).exists()
        )
        self.assertTrue(
            Attendance.objects.filter(
                child=self.child,
                date=today,
                group_snapshot=self.group,
            ).exists()
        )

    def test_additional_group_reason_uses_selected_group(self):
        today = timezone.localdate()
        second_trainer = Trainer.objects.create(full_name="Тренер второй группы")
        second_group = Group.objects.create(
            name="Вторая группа",
            trainer=second_trainer,
        )
        ScheduleSlot.objects.create(
            group=second_group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("attendance_reason"),
            {
                "child_id": self.child.pk,
                "group_id": second_group.pk,
                "kind": AttendanceReason.Kind.SICK,
                "date_from": today.isoformat(),
                "date_to": today.isoformat(),
                "comment": "Справка будет позже",
            },
        )
        self.assertEqual(response.status_code, 200)
        mark = Attendance.objects.get(child=self.child, date=today)
        self.assertEqual(mark.group_snapshot, second_group)
        self.assertEqual(mark.trainer_snapshot, second_trainer)
        self.assertEqual(mark.status, Attendance.Status.SICK)

    def test_attendance_rejects_group_without_membership(self):
        today = timezone.localdate()
        foreign_group = Group.objects.create(
            name="Чужая группа",
            trainer=self.trainer,
        )
        self.client.login(username="admin", password="TestPass123!")
        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": foreign_group.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.ABSENT,
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "group_membership_required")
        self.assertFalse(Attendance.objects.filter(child=self.child, date=today).exists())

    def test_paid_groups_keep_independent_subscription_session_pools(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Вторая платная группа",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        primary_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("6000"),
        )
        second_subscription = Subscription.objects.create(
            child=self.child,
            group=second_group,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=30),
            sessions_total=4,
            price=Decimal("3500"),
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=1),
            group_snapshot=self.group,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=1),
            group_snapshot=second_group,
            status=Attendance.Status.PRESENT,
        )

        self.assertEqual(
            self.child.active_subscription(self.group),
            primary_subscription,
        )
        self.assertEqual(
            self.child.active_subscription(second_group),
            second_subscription,
        )
        self.assertEqual(self.child.sessions_left(self.group), 7)
        self.assertEqual(self.child.sessions_left(second_group), 3)

    def test_additional_paid_group_does_not_use_primary_subscription(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Вторая платная без абонемента",
            trainer=self.trainer,
            single_session_price=Decimal("1000"),
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("6000"),
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": second_group.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "debt_required")
        self.assertFalse(
            Attendance.objects.filter(
                child=self.child,
                date=today,
                group_snapshot=second_group,
            ).exists()
        )

    def test_group_change_backfills_legacy_subscription_to_previous_group(self):
        today = timezone.localdate()
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("6000"),
        )
        Subscription.objects.filter(pk=subscription.pk).update(group=None)

        second_group = Group.objects.create(
            name="Новая основная",
            trainer=self.trainer,
        )
        self.child.group = second_group
        self.child.save(update_fields=["group"])

        subscription.refresh_from_db()
        self.assertEqual(subscription.group, self.group)
        self.assertIsNone(self.child.active_subscription(second_group))
        self.assertEqual(
            self.child.active_subscription(self.group),
            subscription,
        )

    def test_non_subscription_membership_marks_without_debt(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Персональная группа",
            trainer=self.trainer,
            single_session_price=Decimal("1500"),
        )
        ScheduleSlot.objects.create(
            group=second_group,
            weekday=today.weekday(),
            start_time=time(19, 0),
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        self.client.login(username="admin", password="TestPass123!")

        page = self.client.get(
            reverse("attendance"),
            {
                "group_id": second_group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )
        row = next(
            item
            for item in page.context["children_data"]
            if item["child"].pk == self.child.pk
        )
        self.assertFalse(row["requires_subscription"])
        self.assertEqual(
            row["attendance_entries"][0]["subscription_state"],
            "not_required",
        )
        self.assertContains(page, 'data-athlete-sessions-not-required')

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "group_id": second_group.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )
        self.assertEqual(response.status_code, 200)
        mark = Attendance.objects.get(
            child=self.child,
            date=today,
            group_snapshot=second_group,
        )
        self.assertEqual(mark.charge_amount, Decimal("0"))

    def test_non_subscription_group_does_not_spend_subscription_sessions(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Хореография без абонемента",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("6000"),
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=second_group,
            status=Attendance.Status.PRESENT,
        )
        self.assertEqual(self.child.sessions_left(), 8)

        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=self.group,
            status=Attendance.Status.PRESENT,
        )
        self.assertEqual(self.child.sessions_left(), 7)

    def test_group_delete_is_blocked_by_additional_membership_history(self):
        second_group = Group.objects.create(
            name="Группа с дополнительным членством",
            trainer=self.trainer,
        )
        membership = ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        self.client.login(username="admin", password="TestPass123!")

        active_response = self.client.post(
            reverse("group_delete", args=[second_group.pk]),
        )
        self.assertRedirects(active_response, reverse("group_list"))
        self.assertTrue(Group.objects.filter(pk=second_group.pk).exists())

        membership.archived_at = timezone.localdate()
        membership.save(update_fields=["archived_at"])
        archived_response = self.client.post(
            reverse("group_delete", args=[second_group.pk]),
        )
        self.assertRedirects(archived_response, reverse("group_list"))
        self.assertTrue(Group.objects.filter(pk=second_group.pk).exists())

    def test_group_edit_freezes_additional_membership_attendance_history(self):
        old_trainer = self.trainer
        new_trainer = Trainer.objects.create(full_name="Новый тренер группы")
        second_group = Group.objects.create(
            name="Группа для смены тренера",
            trainer=old_trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        mark = Attendance.objects.create(
            child=self.child,
            date=timezone.localdate() - timedelta(days=1),
            group_snapshot=second_group,
            status=Attendance.Status.PRESENT,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("group_edit", args=[second_group.pk]),
            {
                "name": second_group.name,
                "trainer": new_trainer.pk,
                "capacity": "",
                "subscription_tariffs": [],
                "single_session_price": "0",
                "is_active": "on",
                "schedule-TOTAL_FORMS": "0",
                "schedule-INITIAL_FORMS": "0",
                "schedule-MIN_NUM_FORMS": "0",
                "schedule-MAX_NUM_FORMS": "1000",
            },
        )
        self.assertRedirects(response, reverse("group_list"))

        second_group.refresh_from_db()
        mark.refresh_from_db()
        self.assertEqual(second_group.trainer, new_trainer)
        self.assertEqual(mark.group_snapshot, second_group)
        self.assertEqual(mark.trainer_snapshot, old_trainer)
        self.assertEqual(mark.salary_rate_snapshot, second_group.salary_rate)

    def test_invalid_group_edit_does_not_freeze_attendance_history(self):
        new_trainer = Trainer.objects.create(full_name="Не сохранённый тренер")
        mark = Attendance.objects.create(
            child=self.child,
            date=timezone.localdate() - timedelta(days=1),
            group_snapshot=self.group,
            status=Attendance.Status.PRESENT,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("group_edit", args=[self.group.pk]),
            {
                "name": "",
                "trainer": new_trainer.pk,
                "capacity": "",
                "subscription_tariffs": [],
                "single_session_price": "0",
                "is_active": "on",
                "schedule-TOTAL_FORMS": "0",
                "schedule-INITIAL_FORMS": "0",
                "schedule-MIN_NUM_FORMS": "0",
                "schedule-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.group.refresh_from_db()
        mark.refresh_from_db()
        self.assertEqual(self.group.trainer, self.trainer)
        self.assertIsNone(mark.trainer_snapshot_id)
        self.assertIsNone(mark.salary_rate_snapshot)

    def test_statistics_count_additional_group_membership_and_its_marks(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Статистика дополнительной группы",
            trainer=self.trainer,
        )
        ScheduleSlot.objects.create(
            group=second_group,
            weekday=today.weekday(),
            start_time=time(19, 0),
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=second_group,
            status=Attendance.Status.PRESENT,
        )
        self.group.is_active = False
        self.group.save(update_fields=["is_active"])
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.get(
            reverse("statistics"),
            {"month": today.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)
        row = next(
            item
            for item in response.context["groups_stats"]
            if item["group"].pk == second_group.pk
        )
        self.assertEqual(row["kids"], 1)
        self.assertEqual(row["present"], 1)
        self.assertGreaterEqual(row["sessions"], 1)
        self.assertEqual(response.context["unassigned_children"], 0)

    def test_membership_subscription_mode_can_be_changed_after_creation(self):
        second_group = Group.objects.create(
            name="Группа с переключаемым абонементом",
            trainer=self.trainer,
        )
        membership = ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        self.client.login(username="admin", password="TestPass123!")

        disable = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "set_membership_subscription_mode",
                "membership_id": membership.pk,
                "requires_subscription": "0",
            },
        )
        self.assertRedirects(
            disable,
            reverse("child_card", args=[self.child.pk]),
        )
        membership.refresh_from_db()
        self.assertFalse(membership.requires_subscription)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="child.group_membership.subscription_mode",
                object_id=str(self.child.pk),
            ).exists()
        )

        page = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertContains(page, "Без абонемента")
        self.assertContains(page, "data-membership-subscription-mode")

        enable = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "set_membership_subscription_mode",
                "membership_id": membership.pk,
                "requires_subscription": "1",
            },
        )
        self.assertRedirects(
            enable,
            reverse("child_card", args=[self.child.pk]),
        )
        membership.refresh_from_db()
        self.assertTrue(membership.requires_subscription)

    def test_child_card_heatmap_keeps_two_group_marks_on_same_day(self):
        today = timezone.localdate()
        second_group = Group.objects.create(
            name="Вторая группа для heat-map",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=False,
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=self.group,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            child=self.child,
            date=today,
            group_snapshot=second_group,
            status=Attendance.Status.ABSENT,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period_stats"]["present"], 1)
        self.assertEqual(response.context["period_stats"]["absent"], 1)
        today_cell = next(
            day
            for week in response.context["weeks"]
            for day in week["days"]
            if day and day["date"] == today
        )
        self.assertTrue(today_cell["is_multi"])
        self.assertEqual(today_cell["mark_count"], 2)
        self.assertIn(self.group.name, today_cell["status_label"])
        self.assertIn(second_group.name, today_cell["status_label"])
        self.assertContains(response, 'data-multi-attendance="2"')

    def test_archiving_primary_membership_promotes_other_group(self):
        second_trainer = Trainer.objects.create(
            full_name="Дополнительный тренер",
        )
        second_group = Group.objects.create(
            name="Дополнительная группа",
            trainer=second_trainer,
        )
        primary = self.child.group_memberships.get(
            group=self.group,
        )
        additional = ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            is_primary=False,
        )
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "archive_group_membership",
                "membership_id": primary.pk,
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )

        self.child.refresh_from_db()
        primary.refresh_from_db()
        additional.refresh_from_db()
        self.assertIsNotNone(primary.archived_at)
        self.assertFalse(primary.is_primary)
        self.assertTrue(additional.is_primary)
        self.assertEqual(self.child.group, second_group)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="child.group_membership.archive",
                object_id=str(self.child.pk),
            ).exists()
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

    def test_trainer_archive_is_explicit_filterable_and_reversible(self):
        archived = Trainer.objects.create(
            full_name="Тренер из архива",
            is_active=False,
        )
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        active_page = self.client.get(reverse("trainer_list"))
        self.assertEqual(active_page.status_code, 200)
        self.assertContains(active_page, self.trainer.full_name)
        self.assertNotContains(active_page, archived.full_name)
        self.assertContains(active_page, 'data-trainer-filters')
        self.assertContains(active_page, 'name="action" value="archive"')
        self.assertNotContains(
            active_page,
            reverse("trainer_delete", args=[self.trainer.pk]),
        )

        archive_response = self.client.post(
            reverse("trainer_list"),
            {
                "action": "archive",
                "trainer_id": str(self.trainer.pk),
            },
        )
        self.assertRedirects(
            archive_response,
            f"{reverse('trainer_list')}?state=archive",
        )
        self.trainer.refresh_from_db()
        self.group.refresh_from_db()
        self.assertFalse(self.trainer.is_active)
        self.assertEqual(self.group.trainer_id, self.trainer.pk)

        archive_page = self.client.get(
            reverse("trainer_list"),
            {"state": "archive"},
        )
        self.assertContains(archive_page, self.trainer.full_name)
        self.assertContains(archive_page, archived.full_name)
        self.assertContains(archive_page, 'name="action" value="restore"')

        restore_response = self.client.post(
            reverse("trainer_list"),
            {
                "action": "restore",
                "trainer_id": str(self.trainer.pk),
            },
        )
        self.assertRedirects(
            restore_response,
            f"{reverse('trainer_list')}?state=active",
        )
        self.trainer.refresh_from_db()
        self.assertTrue(self.trainer.is_active)

    def test_legacy_delete_routes_archive_and_preserve_history(self):
        today = timezone.localdate()
        subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )
        payment = Payment.objects.create(
            child=self.child,
            subscription=subscription,
            amount=Decimal("5000"),
            date=today,
            created_by=self.admin,
        )
        mark = Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )

        self.client.login(username="admin", password="TestPass123!")

        card = self.client.get(reverse("child_card", args=[self.child.pk]))
        self.assertNotContains(
            card,
            reverse("child_delete", args=[self.child.pk]),
        )

        child_response = self.client.post(
            reverse("child_delete", args=[self.child.pk]),
        )
        self.assertRedirects(child_response, reverse("attendance"))

        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.ARCHIVED)
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        self.assertTrue(Subscription.objects.filter(pk=subscription.pk).exists())
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertTrue(Attendance.objects.filter(pk=mark.pk).exists())

        trainer_response = self.client.post(
            reverse("trainer_delete", args=[self.trainer.pk]),
        )
        self.assertRedirects(trainer_response, reverse("trainer_list"))

        self.trainer.refresh_from_db()
        self.group.refresh_from_db()
        self.assertFalse(self.trainer.is_active)
        self.assertEqual(self.group.trainer_id, self.trainer.pk)
        self.assertTrue(Trainer.objects.filter(pk=self.trainer.pk).exists())

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

    def test_malformed_optional_object_ids_do_not_crash_pages(self):
        competition = Competition.objects.create(
            name="Проверка некорректного id",
            date=timezone.localdate(),
        )
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        cases = (
            ("attendance", {"group_id": "not-a-pk"}),
            ("payments", {"edit_tariff": "not-a-pk"}),
            ("payments", {"edit_subscription": "not-a-pk"}),
            ("expenses", {"edit": "not-a-pk"}),
            ("competitions", {"competition": "not-a-pk"}),
            ("competitions", {"edit_competition": "not-a-pk"}),
            (
                "competitions",
                {
                    "competition": competition.pk,
                    "edit_apparatus": "not-a-pk",
                },
            ),
            (
                "competitions",
                {
                    "competition": competition.pk,
                    "edit_entry": "not-a-pk",
                },
            ),
            ("applications", {"edit": "not-a-pk"}),
            ("newcomers", {"edit": "not-a-pk"}),
            ("calendar", {"edit": "not-a-pk"}),
            ("trainer_list", {"edit": "not-a-pk"}),
            ("group_list", {"edit": "not-a-pk"}),
            ("camps", {"edit": "not-a-pk"}),
        )

        for route_name, query in cases:
            with self.subTest(route_name=route_name, query=query):
                response = self.client.get(
                    reverse(route_name),
                    query,
                )
                self.assertEqual(response.status_code, 200)

    def test_malformed_explicit_intake_edit_id_returns_404(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        for route_name in ("applications", "newcomers"):
            with self.subTest(route_name=route_name):
                response = self.client.post(
                    reverse(route_name),
                    {
                        "action": "save",
                        "form_mode": "edit",
                        "editing_id": "not-a-pk",
                    },
                )
                self.assertEqual(response.status_code, 404)

    def test_base_uses_single_explicit_dropdown_and_modal_controller(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.get(reverse("attendance"))
        self.assertEqual(response.status_code, 200)

        for target in (
            "dropdown-clients",
            "dropdown-team",
            "dropdown-finance",
            "dropdown-stats",
            "dropdown-events",
            "dropdown-user",
        ):
            self.assertContains(
                response,
                f'data-dropdown-target="{target}"',
                count=1,
            )

        self.assertContains(response, 'id="dropdown-user"', count=1)
        self.assertNotContains(response, "btnText.includes")
        self.assertNotContains(
            response,
            "wrapper.querySelector('[data-dropdown-menu]')",
        )

        app_js = (
            Path(__file__).resolve().parent
            / "static"
            / "crm"
            / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn('event.key !== "Escape"', app_js)
        self.assertIn(
            'window.addEventListener("scroll", closeAllDropdowns, true)',
            app_js,
        )
        self.assertIn(
            'window.addEventListener("resize", closeAllDropdowns)',
            app_js,
        )
        self.assertIn('toggle.dataset.dropdownTarget', app_js)

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

    def test_required_documents_alert_missing_expiry_and_expired(self):
        today = timezone.localdate()

        self.assertEqual(
            {item["key"] for item in self.child.document_alerts(today)},
            {"certificate", "insurance", "permission"},
        )

        self.child.certificate = "certificates/reference.jpg"
        self.child.insurance = "child_documents/insurance/policy.pdf"
        self.child.permission = "child_documents/permission/permit.pdf"
        self.child.certificate_valid_until = today + timedelta(days=30)
        self.child.insurance_valid_until = today + timedelta(days=30)
        self.child.permission_valid_until = today + timedelta(days=30)
        self.child.save(update_fields=[
            "certificate",
            "insurance",
            "permission",
            "certificate_valid_until",
            "insurance_valid_until",
            "permission_valid_until",
        ])

        self.assertEqual(self.child.document_alerts(today), [])

        self.child.insurance_valid_until = today - timedelta(days=1)
        self.child.save(update_fields=["insurance_valid_until"])
        alerts = self.child.document_alerts(today)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["key"], "insurance")
        self.assertEqual(alerts[0]["state"], "expired")

        self.child.insurance_valid_until = None
        self.child.save(update_fields=["insurance_valid_until"])
        alerts = self.child.document_alerts(today)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["state"], "no_expiry")

    def test_child_document_manage_uploads_and_deletes_insurance(self):
        today = timezone.localdate()
        valid_until = today + timedelta(days=60)
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse(
                "child_certificate_manage",
                args=[self.child.pk],
            ),
            {
                "action": "upload",
                "kind": "insurance",
                "valid_until": valid_until.isoformat(),
                "document": SimpleUploadedFile(
                    "insurance.pdf",
                    b"%PDF-test-insurance",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertTrue(self.child.insurance)
        self.assertEqual(self.child.insurance_valid_from, today)
        self.assertEqual(
            self.child.insurance_valid_until,
            valid_until,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="child.document.upload",
                object_id=str(self.child.pk),
            ).exists()
        )

        download = self.client.get(
            reverse(
                "child_document",
                args=[self.child.pk, "insurance"],
            ),
        )
        self.assertEqual(download.status_code, 200)

        response = self.client.post(
            reverse(
                "child_certificate_manage",
                args=[self.child.pk],
            ),
            {
                "action": "delete",
                "kind": "insurance",
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertFalse(self.child.insurance)
        self.assertIsNone(self.child.insurance_valid_from)
        self.assertIsNone(self.child.insurance_valid_until)

    def test_document_period_defaults_to_six_months_and_allows_manual_end(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        start = datetime(2026, 8, 31).date()

        response = self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {
                "action": "upload",
                "kind": "permission",
                "valid_from": start.isoformat(),
                "valid_until": "",
                "document": SimpleUploadedFile(
                    "permission.pdf",
                    b"%PDF-test-permission",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertEqual(self.child.permission_valid_from, start)
        self.assertEqual(
            self.child.permission_valid_until,
            datetime(2027, 2, 28).date(),
        )

        manual_end = datetime(2027, 4, 15).date()
        response = self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {
                "action": "upload",
                "kind": "permission",
                "valid_from": start.isoformat(),
                "valid_until": manual_end.isoformat(),
                "document": SimpleUploadedFile(
                    "permission-manual.pdf",
                    b"%PDF-test-permission-manual",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertEqual(self.child.permission_valid_until, manual_end)

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertContains(card, 'name="valid_from"')
        self.assertContains(card, 'data-document-period')
        self.assertContains(card, "6 месяцев от даты начала")

    def test_document_period_rejects_end_before_start(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        start = datetime(2026, 9, 10).date()
        end = datetime(2026, 9, 9).date()

        response = self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {
                "action": "upload",
                "kind": "insurance",
                "valid_from": start.isoformat(),
                "valid_until": end.isoformat(),
                "document": SimpleUploadedFile(
                    "bad-period.pdf",
                    b"%PDF-bad-period",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        self.child.refresh_from_db()
        self.assertFalse(self.child.insurance)
        self.assertIsNone(self.child.insurance_valid_from)
        self.assertIsNone(self.child.insurance_valid_until)

        future_start = timezone.localdate() + timedelta(days=1)
        self.child.insurance = "child_documents/insurance/future.pdf"
        self.child.insurance_valid_from = future_start
        self.child.insurance_valid_until = future_start + timedelta(days=30)
        self.child.save(update_fields=[
            "insurance",
            "insurance_valid_from",
            "insurance_valid_until",
        ])
        status = {
            item["key"]: item
            for item in self.child.required_document_statuses(timezone.localdate())
        }["insurance"]
        self.assertEqual(status["state"], "not_started")

    def test_child_card_and_attendance_use_document_alert(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(card.status_code, 200)
        self.assertContains(card, 'data-child-documents')
        self.assertContains(
            card,
            'data-child-document="certificate"',
        )
        self.assertContains(
            card,
            'data-child-document="insurance"',
        )
        self.assertContains(
            card,
            'data-child-document="permission"',
        )
        self.assertContains(card, 'name="valid_until"')

        attendance = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )
        self.assertEqual(attendance.status_code, 200)
        self.assertContains(
            attendance,
            'data-athlete-indicator="documents-alert"',
        )
        self.assertNotContains(
            attendance,
            'data-athlete-indicator="certificate"',
        )

        valid_until = today + timedelta(days=30)
        self.child.certificate = "certificates/reference.jpg"
        self.child.insurance = "child_documents/insurance/policy.pdf"
        self.child.permission = "child_documents/permission/permit.pdf"
        self.child.certificate_valid_until = valid_until
        self.child.insurance_valid_until = valid_until
        self.child.permission_valid_until = valid_until
        self.child.save(update_fields=[
            "certificate",
            "insurance",
            "permission",
            "certificate_valid_until",
            "insurance_valid_until",
            "permission_valid_until",
        ])

        attendance = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )
        self.assertNotContains(
            attendance,
            'data-athlete-indicator="documents-alert"',
        )

    def test_child_card_can_add_training_camp_with_explicit_type(self):
        from .models import Camp

        start = timezone.localdate() + timedelta(days=10)
        end = start + timedelta(days=7)
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "add_camp",
                "camp-kind": Camp.Kind.TRAINING,
                "camp-camp_name": "Летние сборы",
                "camp-start_date": start.isoformat(),
                "camp-end_date": end.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        stay = self.child.camp_stays.select_related("camp").get()
        self.assertEqual(stay.camp.kind, Camp.Kind.TRAINING)
        self.assertEqual(stay.camp.name, "Летние сборы")

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertContains(card, "Лагеря и сборы")
        self.assertContains(card, "Сборы")
        self.assertContains(card, 'name="camp-kind"')

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

    def test_child_card_boss_can_assign_linked_task(self):
        due_date = timezone.localdate() + timedelta(days=2)
        other_child = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2016,
            group=self.group,
        )
        ManagerTask.objects.create(
            title="Задача другого спортсмена",
            child=other_child,
            assignee=self.admin,
            created_by=self.boss,
            due_date=due_date,
        )

        self.client.login(
            username="boss",
            password="TestPass123!",
        )

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(card.status_code, 200)
        self.assertContains(card, "data-child-task-button")
        self.assertContains(card, 'id="child-task-modal"')
        self.assertContains(card, 'name="task-title"')
        self.assertContains(card, 'name="task-description"')
        self.assertContains(card, 'name="task-due_date"')
        self.assertContains(card, 'name="task-assignee"')
        self.assertContains(card, "Поставить задачу")
        self.assertContains(card, "Дата выполнения")
        self.assertContains(card, "Комментарий")
        self.assertContains(card, "Ответственный")
        self.assertNotContains(card, "Задача другого спортсмена")

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "create_child_task",
                "task-title": "Позвонить родителю спортсмена",
                "task-description": "Уточнить участие в соревнованиях",
                "task-assignee": self.admin.pk,
                "task-due_date": due_date.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        task = ManagerTask.objects.get(
            title="Позвонить родителю спортсмена",
        )
        self.assertEqual(task.child, self.child)
        self.assertEqual(task.created_by, self.boss)
        self.assertEqual(task.assignee, self.admin)
        self.assertEqual(task.due_date, due_date)
        self.assertEqual(
            task.description,
            "Уточнить участие в соревнованиях",
        )
        self.assertEqual(
            self.child.manager_tasks.get(pk=task.pk),
            task,
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.admin,
                task=task,
                kind=Notification.Kind.TASK_CREATED,
                read_at__isnull=True,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.boss,
                action="task.create_child",
                object_id=str(task.pk),
            ).exists()
        )

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertContains(
            card,
            f'data-child-task="{task.pk}"',
        )
        self.assertContains(
            card,
            "Позвонить родителю спортсмена",
        )
        self.assertContains(
            card,
            "Уточнить участие в соревнованиях",
        )
        self.assertContains(
            card,
            due_date.strftime("%d.%m.%Y"),
        )
        self.assertNotContains(
            card,
            "Задача другого спортсмена",
        )

    def test_child_card_manager_task_forces_self_and_requires_due_date(self):
        due_date = timezone.localdate() + timedelta(days=1)
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(card.status_code, 200)
        self.assertNotContains(
            card,
            'name="task-assignee"',
        )

        response = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "create_child_task",
                "task-title": "Проверить документы",
                "task-description": "Позвонить после тренировки",
                "task-assignee": self.senior.pk,
                "task-due_date": due_date.isoformat(),
            },
        )
        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        task = ManagerTask.objects.get(
            title="Проверить документы",
        )
        self.assertEqual(task.child, self.child)
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.assignee, self.admin)
        self.assertEqual(task.due_date, due_date)

        invalid = self.client.post(
            reverse("child_card", args=[self.child.pk]),
            {
                "action": "create_child_task",
                "task-title": "Задача без даты",
                "task-description": "",
                "task-assignee": self.senior.pk,
                "task-due_date": "",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(
            ManagerTask.objects.filter(
                title="Задача без даты",
            ).exists()
        )
        self.assertIn(
            "due_date",
            invalid.context["task_form"].errors,
        )
        self.assertContains(
            invalid,
            'id="child-task-modal"',
        )
        self.assertContains(
            invalid,
            'class="modal open"',
        )


    def test_attendance_mark_is_saved(self):
        today = timezone.localdate()
        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )
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
        
    def test_attendance_present_requires_explicit_debt_formalization(self):
        today = timezone.localdate()
        self.group.single_session_price = Decimal("750")
        self.group.save(update_fields=["single_session_price"])
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        blocked = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json()["code"],
            "debt_required",
        )
        self.assertFalse(
            Attendance.objects.filter(
                child=self.child,
                date=today,
            ).exists()
        )

        allowed = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
                "allow_debt": "1",
            },
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.json()["debt_formalized"])
        attendance = Attendance.objects.get(
            child=self.child,
            date=today,
        )
        self.assertEqual(
            attendance.status,
            Attendance.Status.PRESENT,
        )
        self.assertEqual(
            attendance.charge_amount,
            Decimal("750"),
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="attendance.debt",
                object_id=str(attendance.pk),
            ).exists()
        )

    def test_attendance_debt_requires_configured_price(self):
        today = timezone.localdate()
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
                "allow_debt": "1",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["code"],
            "debt_price_required",
        )
        self.assertFalse(
            Attendance.objects.filter(
                child=self.child,
                date=today,
            ).exists()
        )

    def test_attendance_absence_without_subscription_remains_allowed(self):
        today = timezone.localdate()
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.ABSENT,
            },
        )

        self.assertEqual(response.status_code, 200)
        attendance = Attendance.objects.get(
            child=self.child,
            date=today,
        )
        self.assertEqual(
            attendance.status,
            Attendance.Status.ABSENT,
        )
        self.assertEqual(
            attendance.charge_amount,
            Decimal("0"),
        )

    def test_attendance_reason_period_creates_sick_marks_and_document(self):
        start = timezone.localdate()
        end = start + timedelta(days=2)
        for class_date in (
            start,
            start + timedelta(days=1),
            end,
        ):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=class_date.weekday(),
                start_time=time(18, 0),
            )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.post(
            reverse("attendance_reason"),
            {
                "child_id": self.child.pk,
                "kind": AttendanceReason.Kind.SICK,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "comment": "ОРВИ",
                "document": SimpleUploadedFile(
                    "sick-note.pdf",
                    b"%PDF-test",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["attendance_count"], 3)

        reason = AttendanceReason.objects.get(
            child=self.child,
            kind=AttendanceReason.Kind.SICK,
        )
        self.assertEqual(reason.date_from, start)
        self.assertEqual(reason.date_to, end)
        self.assertEqual(reason.comment, "ОРВИ")
        self.assertTrue(reason.document.name.endswith("sick-note.pdf"))
        self.assertEqual(reason.created_by, self.admin)

        marks = list(
            Attendance.objects
            .filter(
                child=self.child,
                reason=reason,
            )
            .order_by("date")
        )
        self.assertEqual(
            [mark.date for mark in marks],
            [
                start,
                start + timedelta(days=1),
                end,
            ],
        )
        self.assertTrue(
            all(
                mark.status == Attendance.Status.SICK
                and mark.comment == "ОРВИ"
                and mark.charge_amount == Decimal("0")
                for mark in marks
            )
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="attendance.reason",
                object_id=str(reason.pk),
            ).exists()
        )
        reason.document.delete(save=False)

    def test_attendance_reason_period_uses_only_real_class_dates(self):
        start = timezone.localdate()
        middle = start + timedelta(days=1)
        end = start + timedelta(days=2)
        for class_date in (start, end):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=class_date.weekday(),
                start_time=time(18, 0),
            )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.post(
            reverse("attendance_reason"),
            {
                "child_id": self.child.pk,
                "kind": AttendanceReason.Kind.FROZEN,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "comment": "Заявление родителя",
            },
        )

        self.assertEqual(response.status_code, 200)
        reason = AttendanceReason.objects.get(
            child=self.child,
            kind=AttendanceReason.Kind.FROZEN,
        )
        self.assertEqual(
            list(
                Attendance.objects
                .filter(reason=reason)
                .order_by("date")
                .values_list("date", flat=True)
            ),
            [start, end],
        )
        self.assertFalse(
            Attendance.objects.filter(
                child=self.child,
                date=middle,
            ).exists()
        )

    def test_attendance_reason_ui_has_compact_detail_form(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
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
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'id="attendance-reason-modal"',
        )
        self.assertContains(
            response,
            'data-attendance-choice="reason_excused"',
        )
        self.assertContains(
            response,
            'data-attendance-choice="reason_sick"',
        )
        self.assertContains(
            response,
            'data-attendance-choice="reason_frozen"',
        )
        self.assertContains(response, 'name="date_from"')
        self.assertContains(response, 'name="date_to"')
        self.assertContains(response, 'name="comment"')
        self.assertContains(response, 'name="document"')
        self.assertContains(response, "openReasonModal")

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

    def test_child_card_shows_general_and_personal_competition_documents(self):
        competition = Competition.objects.create(
            name="Кубок с документами",
            date=timezone.localdate(),
            city="Москва",
        )
        CompetitionEntry.objects.create(
            child=self.child,
            competition=competition,
            category="2015",
        )
        other_child = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
        )
        general_document = CompetitionDocument.objects.create(
            competition=competition,
            title="Положение соревнования",
            file=SimpleUploadedFile(
                "rules.pdf",
                b"%PDF-general",
                content_type="application/pdf",
            ),
        )
        personal_document = CompetitionDocument.objects.create(
            competition=competition,
            child=self.child,
            title="Грамота Анны",
            file=SimpleUploadedFile(
                "anna.pdf",
                b"%PDF-personal",
                content_type="application/pdf",
            ),
        )
        foreign_document = CompetitionDocument.objects.create(
            competition=competition,
            child=other_child,
            title="Грамота Марии",
            file=SimpleUploadedFile(
                "maria.pdf",
                b"%PDF-foreign",
                content_type="application/pdf",
            ),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Документы и награды")
        self.assertContains(response, "Положение соревнования")
        self.assertContains(response, "Грамота Анны")
        self.assertNotContains(response, "Грамота Марии")
        self.assertContains(
            response,
            reverse(
                "competition_document_download",
                args=[general_document.pk],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "competition_document_download",
                args=[personal_document.pk],
            ),
        )

        for document in (
            general_document,
            personal_document,
            foreign_document,
        ):
            document.file.delete(save=False)

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
            "subscription-group": self.group.pk,
            "subscription-tariff": tariff.pk, "subscription-start_date": start.isoformat(),
            "subscription-promo": "", "subscription-is_active": "on",
        })
        subscription = Subscription.objects.get(child=self.child)
        self.assertEqual(subscription.price, Decimal("6000"))
        self.assertEqual(subscription.end_date, start + timedelta(days=30))

    def test_subscription_tariff_must_match_child_primary_group(self):
        allowed_tariff = Tariff.objects.create(
            name="Тариф группы",
            price=Decimal("5000"),
            sessions_total=8,
            duration_days=30,
        )
        foreign_tariff = Tariff.objects.create(
            name="Чужой тариф",
            price=Decimal("9000"),
            sessions_total=12,
            duration_days=30,
        )
        self.group.subscription_tariffs.add(allowed_tariff)
        start = timezone.localdate()
        self.client.login(username="admin", password="TestPass123!")

        blocked = self.client.post(
            reverse("payments"),
            {
                "action": "save_subscription",
                "subscription-child": self.child.pk,
                "subscription-group": self.group.pk,
                "subscription-tariff": foreign_tariff.pk,
                "subscription-start_date": start.isoformat(),
                "subscription-promo": "",
                "subscription-is_active": "on",
            },
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(
            Subscription.objects.filter(child=self.child).exists()
        )
        self.assertContains(
            blocked,
            "не назначен группе",
        )

        allowed = self.client.post(
            reverse("payments"),
            {
                "action": "save_subscription",
                "subscription-child": self.child.pk,
                "subscription-group": self.group.pk,
                "subscription-tariff": allowed_tariff.pk,
                "subscription-start_date": start.isoformat(),
                "subscription-promo": "",
                "subscription-is_active": "on",
            },
        )
        self.assertRedirects(allowed, reverse("payments"))
        subscription = Subscription.objects.get(child=self.child)
        self.assertEqual(subscription.tariff, allowed_tariff)
        self.assertEqual(subscription.price, Decimal("5000"))

        modal = self.client.get(
            reverse("payments"),
            {
                "child": self.child.pk,
                "new_subscription": "1",
            },
        )
        self.assertContains(
            modal,
            f'data-primary-group-id="{self.group.pk}"',
        )
        self.assertContains(
            modal,
            f'data-group-ids="{self.group.pk}"',
        )
        self.assertContains(
            modal,
            'data-tariffs-configured="1"',
        )
        self.assertContains(modal, "applyGroupAvailability")
        self.assertContains(modal, "applyTariffAvailability")
        self.assertContains(
            modal,
            "Для выбранной группы нет активного тарифа",
        )

    def test_subscription_is_bound_to_selected_membership_group(self):
        second_group = Group.objects.create(
            name="Дополнительная платная",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        primary_tariff = Tariff.objects.create(
            name="Основная группа",
            price=Decimal("5000"),
            sessions_total=8,
            duration_days=30,
        )
        second_tariff = Tariff.objects.create(
            name="Дополнительная группа",
            price=Decimal("3500"),
            sessions_total=4,
            duration_days=30,
        )
        self.group.subscription_tariffs.add(primary_tariff)
        second_group.subscription_tariffs.add(second_tariff)
        start = timezone.localdate()
        self.client.login(username="admin", password="TestPass123!")

        second_response = self.client.post(
            reverse("payments"),
            {
                "action": "save_subscription",
                "subscription-child": self.child.pk,
                "subscription-group": second_group.pk,
                "subscription-tariff": second_tariff.pk,
                "subscription-start_date": start.isoformat(),
                "subscription-promo": "",
                "subscription-is_active": "on",
            },
        )
        self.assertRedirects(second_response, reverse("payments"))
        second_subscription = Subscription.objects.get(
            child=self.child,
            group=second_group,
        )
        self.assertTrue(second_subscription.is_active)

        primary_response = self.client.post(
            reverse("payments"),
            {
                "action": "save_subscription",
                "subscription-child": self.child.pk,
                "subscription-group": self.group.pk,
                "subscription-tariff": primary_tariff.pk,
                "subscription-start_date": start.isoformat(),
                "subscription-promo": "",
                "subscription-is_active": "on",
            },
        )
        self.assertRedirects(primary_response, reverse("payments"))

        second_subscription.refresh_from_db()
        primary_subscription = Subscription.objects.get(
            child=self.child,
            group=self.group,
        )
        self.assertTrue(primary_subscription.is_active)
        self.assertTrue(second_subscription.is_active)

    def test_legacy_add_subscription_deactivates_only_same_group_overlap(self):
        second_group = Group.objects.create(
            name="Дополнительная для legacy add",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        primary_tariff = Tariff.objects.create(
            name="Legacy add primary",
            price=Decimal("5000"),
            sessions_total=8,
            duration_days=30,
        )
        second_tariff = Tariff.objects.create(
            name="Legacy add additional",
            price=Decimal("3000"),
            sessions_total=4,
            duration_days=30,
        )
        self.group.subscription_tariffs.add(primary_tariff)
        second_group.subscription_tariffs.add(second_tariff)

        today = timezone.localdate()
        old_primary = Subscription.objects.create(
            child=self.child,
            group=self.group,
            tariff=primary_tariff,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        additional = Subscription.objects.create(
            child=self.child,
            group=second_group,
            tariff=second_tariff,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=4,
            price=Decimal("3000"),
            is_active=True,
        )
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("add_subscription", args=[self.child.pk]),
            {
                "child": self.child.pk,
                "group": self.group.pk,
                "tariff": primary_tariff.pk,
                "start_date": today.isoformat(),
                "promo": "",
                "is_active": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("child_card", args=[self.child.pk]),
        )
        old_primary.refresh_from_db()
        additional.refresh_from_db()
        self.assertFalse(old_primary.is_active)
        self.assertTrue(additional.is_active)
        self.assertEqual(
            Subscription.objects.filter(
                child=self.child,
                group=self.group,
                is_active=True,
            ).count(),
            1,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="subscription.save",
            ).exists()
        )

    def test_subscription_rejects_non_subscription_membership_group(self):
        personal_group = Group.objects.create(
            name="Персональные",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=personal_group,
            requires_subscription=False,
        )
        tariff = Tariff.objects.create(
            name="Персональный тариф",
            price=Decimal("2500"),
            sessions_total=4,
            duration_days=30,
        )
        personal_group.subscription_tariffs.add(tariff)
        self.client.login(username="admin", password="TestPass123!")

        response = self.client.post(
            reverse("payments"),
            {
                "action": "save_subscription",
                "subscription-child": self.child.pk,
                "subscription-group": personal_group.pk,
                "subscription-tariff": tariff.pk,
                "subscription-start_date": timezone.localdate().isoformat(),
                "subscription-promo": "",
                "subscription-is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Subscription.objects.filter(
                child=self.child,
                group=personal_group,
            ).exists()
        )
        self.assertContains(
            response,
            "не является активной абонементной группой спортсмена",
        )

    def test_new_subscription_defaults_to_primary_group_for_legacy_callers(self):
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )

        self.assertEqual(subscription.group, self.group)

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
            "xl:grid-cols-[minmax(0,1fr)_16rem]",
        )
        self.assertContains(
            response,
            'data-modal="task-modal"',
            count=1,
        )
        self.assertNotContains(response, "На смене:")
        self.assertNotContains(response, "Готовые")


    def test_calendar_day_cells_show_active_and_overdue_counts(self):
        today = timezone.localdate()
        scheduled_at = timezone.now().replace(
            second=0,
            microsecond=0,
        )

        ManagerTask.objects.create(
            title="Активная задача",
            assignee=self.admin,
            created_by=self.boss,
            scheduled_at=scheduled_at,
            due_date=today + timedelta(days=1),
        )
        ManagerTask.objects.create(
            title="Просроченная задача",
            assignee=self.admin,
            created_by=self.boss,
            scheduled_at=scheduled_at,
            due_date=today - timedelta(days=1),
        )
        ManagerTask.objects.create(
            title="Готовая задача",
            assignee=self.admin,
            created_by=self.boss,
            scheduled_at=scheduled_at,
            due_date=today - timedelta(days=1),
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
        day = next(
            item
            for item in response.context["days"]
            if item["date"] == today
        )
        self.assertEqual(day["task_count"], 1)
        self.assertEqual(day["active_count"], 2)
        self.assertEqual(day["overdue_count"], 1)
        self.assertEqual(response.context["month_active_count"], 2)
        self.assertEqual(response.context["month_overdue_count"], 1)
        self.assertContains(response, 'data-day-active-count="2"')
        self.assertContains(response, 'data-day-overdue-count="1"')


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

    def test_profile_saves_attendance_visual_settings_per_user(self):
        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("profile"),
            {
                "action": "attendance_visual",
                "show_attendance_legend": "on",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        profile = StaffProfile.objects.get(user=self.admin)
        self.assertTrue(profile.show_attendance_legend)
        self.assertFalse(profile.show_attendance_today_highlight)
        self.assertFalse(
            profile.show_attendance_subscription_boundary
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="profile.visual",
                object_id=str(profile.pk),
            ).exists()
        )

        self.client.logout()
        self.client.login(
            username="boss",
            password="TestPass123!",
        )
        boss_profile = StaffProfile.objects.get(user=self.boss)
        self.assertTrue(boss_profile.show_attendance_legend)
        self.assertTrue(boss_profile.show_attendance_today_highlight)
        self.assertTrue(
            boss_profile.show_attendance_subscription_boundary
        )

    def test_attendance_respects_visual_profile_settings(self):
        today = timezone.localdate()
        for weekday in range(7):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=weekday,
                start_time=time(18, 0),
            )
        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=1,
            price=Decimal("5000"),
        )

        profile = StaffProfile.objects.get(user=self.admin)
        profile.show_attendance_legend = False
        profile.show_attendance_today_highlight = False
        profile.show_attendance_subscription_boundary = False
        profile.save(update_fields=[
            "show_attendance_legend",
            "show_attendance_today_highlight",
            "show_attendance_subscription_boundary",
        ])

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["attendance_visual"],
            {
                "show_legend": False,
                "highlight_today": False,
                "show_subscription_boundary": False,
            },
        )
        self.assertNotContains(
            response,
            "data-attendance-legend",
        )
        self.assertNotContains(
            response,
            "border-r-2 border-red-500",
        )
        self.assertNotContains(
            response,
            "bg-orange-50 text-[#FF5C35]",
        )

        profile.show_attendance_legend = True
        profile.show_attendance_today_highlight = True
        profile.show_attendance_subscription_boundary = True
        profile.save(update_fields=[
            "show_attendance_legend",
            "show_attendance_today_highlight",
            "show_attendance_subscription_boundary",
        ])
        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )
        self.assertContains(response, "data-attendance-legend")
        self.assertContains(
            response,
            "border-r-2 border-red-500",
        )
        self.assertContains(
            response,
            "bg-orange-50 text-[#FF5C35]",
        )

    def test_lesson_trainer_assignment_splits_group_and_updates_history(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        other_child = Child.objects.create(
            last_name="Петрова",
            first_name="Мария",
            birth_year=2015,
            group=self.group,
        )
        third_child = Child.objects.create(
            last_name="Сидорова",
            first_name="Елена",
            birth_year=2015,
            group=self.group,
        )
        substitute_a = Trainer.objects.create(
            full_name="Тренер Замена А",
        )
        substitute_b = Trainer.objects.create(
            full_name="Тренер Замена Б",
        )
        existing_mark = Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
            salary_rate_snapshot=self.group.salary_rate,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        response = self.client.post(
            reverse("assign_lesson_trainer"),
            {
                "group_id": self.group.pk,
                "lesson_date": today.isoformat(),
                "trainer_id": substitute_a.pk,
                "child_ids": [self.child.pk],
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("assign_lesson_trainer"),
            {
                "group_id": self.group.pk,
                "lesson_date": today.isoformat(),
                "trainer_id": substitute_b.pk,
                "child_ids": [other_child.pk],
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            LessonTrainerAssignment.objects.get(
                group=self.group,
                date=today,
                child=self.child,
            ).trainer,
            substitute_a,
        )
        self.assertEqual(
            LessonTrainerAssignment.objects.get(
                group=self.group,
                date=today,
                child=other_child,
            ).trainer,
            substitute_b,
        )
        self.assertFalse(
            LessonTrainerAssignment.objects.filter(
                group=self.group,
                date=today,
                child=third_child,
            ).exists()
        )

        existing_mark.refresh_from_db()
        self.assertEqual(
            existing_mark.trainer_snapshot,
            substitute_a,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="attendance.trainer_assign",
                object_id=str(self.group.pk),
            ).exists()
        )

    def test_lesson_trainer_assignment_is_used_when_marking_attendance(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        substitute = Trainer.objects.create(
            full_name="Фактический тренер",
        )
        LessonTrainerAssignment.objects.create(
            group=self.group,
            date=today,
            child=self.child,
            trainer=substitute,
            created_by=self.admin,
        )
        Subscription.objects.create(
            child=self.child,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.post(
            reverse("mark_attendance"),
            {
                "child_id": self.child.pk,
                "date": today.isoformat(),
                "status": Attendance.Status.PRESENT,
            },
        )

        self.assertEqual(response.status_code, 200)
        mark = Attendance.objects.get(
            child=self.child,
            date=today,
        )
        self.assertEqual(mark.trainer_snapshot, substitute)

        page = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "day",
                "ref_date": today.isoformat(),
            },
        )
        row = next(
            item
            for item in page.context["children_data"]
            if item["child"].pk == self.child.pk
        )
        entry = row["attendance_entries"][0]
        self.assertEqual(entry["trainer_id"], substitute.pk)
        self.assertTrue(entry["is_substitute_trainer"])
        self.assertContains(page, 'id="lesson-trainer-modal"')
        self.assertContains(page, 'name="child_ids"')
        self.assertContains(page, "Тренеры на дату")
        self.assertContains(page, "Тренер по замене")

    def test_lesson_trainer_assignment_can_reset_selected_children_to_primary(self):
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=self.group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )
        substitute = Trainer.objects.create(
            full_name="Временный тренер",
        )
        assignment = LessonTrainerAssignment.objects.create(
            group=self.group,
            date=today,
            child=self.child,
            trainer=substitute,
            created_by=self.admin,
        )
        mark = Attendance.objects.create(
            child=self.child,
            date=today,
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
            trainer_snapshot=substitute,
            salary_rate_snapshot=self.group.salary_rate,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.post(
            reverse("assign_lesson_trainer"),
            {
                "group_id": self.group.pk,
                "lesson_date": today.isoformat(),
                "trainer_id": "",
                "child_ids": [self.child.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            LessonTrainerAssignment.objects.filter(
                pk=assignment.pk,
            ).exists()
        )
        mark.refresh_from_db()
        self.assertEqual(mark.trainer_snapshot, self.trainer)

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

        first_row = response.context["children_data"][0]
        self.assertEqual(first_row["sessions_used"], 3)
        self.assertEqual(first_row["sessions_left"], 5)
        self.assertEqual(first_row["sessions_total"], 8)
        self.assertContains(
            response,
            "3/8",
        )
        self.assertNotContains(
            response,
            "5/8",
        )
        self.assertContains(response, "data-athlete-primary-row")
        self.assertContains(response, "data-athlete-sessions")
        self.assertContains(response, "data-athlete-meta-row")
        self.assertContains(response, "data-athlete-indicators")
        self.assertContains(response, "data-athlete-subscription-end")

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
        from .forms import SubscriptionForm

        today = timezone.localdate()
        promo_start = today - timedelta(days=4)
        promo_end = today + timedelta(days=4)
        other_group = Group.objects.create(
            name="Другая группа акции",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )

        subscription = Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=10),
            sessions_total=8,
            price=Decimal("5600"),
            promo="Скидка 10%",
            promo_percent=10,
            promo_start_date=promo_start,
            promo_end_date=promo_end,
            is_active=True,
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=3),
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=2),
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
        )
        Attendance.objects.create(
            child=self.child,
            date=today - timedelta(days=1),
            status=Attendance.Status.PRESENT,
            group_snapshot=other_group,
        )

        self.assertEqual(subscription.sessions_used(), 2)
        self.assertEqual(
            self.child.sessions_left(),
            6,
        )

        self.assertEqual(
            self.child.nearest_expiry(),
            subscription.end_date,
        )

        promo = self.child.active_promos()[0]
        self.assertEqual(promo["name"], "Скидка 10%")
        self.assertEqual(promo["percent"], 10)
        self.assertEqual(promo["start_date"], promo_start)
        self.assertEqual(promo["end_date"], promo_end)
        self.assertEqual(promo["sessions_used"], 2)
        self.assertEqual(promo["sessions_total"], 8)

        form_data = {
            "child": self.child.pk,
            "group": self.group.pk,
            "tariff": "",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
            "sessions_total": "8",
            "price": "5600",
            "promo": "Акция без ручного начала",
            "promo_percent": "10",
            "promo_start_date": "",
            "promo_end_date": (today + timedelta(days=10)).isoformat(),
            "is_active": "on",
            "manual_override": "on",
        }
        form = SubscriptionForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form.cleaned_data["promo_start_date"], today)

        invalid_form = SubscriptionForm(
            data={
                **form_data,
                "promo_start_date": (
                    today + timedelta(days=2)
                ).isoformat(),
                "promo_end_date": (
                    today + timedelta(days=1)
                ).isoformat(),
            }
        )
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("promo_end_date", invalid_form.errors)

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        card = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(card.status_code, 200)
        self.assertContains(card, "Скидка 10%")
        self.assertContains(
            card,
            f"{promo_start:%d.%m.%Y} — {promo_end:%d.%m.%Y}",
        )
        self.assertContains(card, "data-child-promo")
        self.assertContains(card, 'data-used="2"')
        self.assertContains(card, 'data-total="8"')
        self.assertContains(card, "2/8")

        payments = self.client.get(reverse("payments"))
        self.assertContains(
            payments,
            'name="subscription-promo_start_date"',
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

    def test_expired_renewal_shows_actual_used_sessions(self):
        today = timezone.localdate()
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        subscription = Subscription.objects.create(
            child=self.child,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )

        for offset, status in (
            (3, Attendance.Status.PRESENT),
            (2, Attendance.Status.ABSENT),
            (1, Attendance.Status.PRESENT),
        ):
            Attendance.objects.create(
                child=self.child,
                date=end_date - timedelta(days=offset),
                status=status,
            )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("payments"),
            {"month": end_date.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        row = next(
            item
            for item in response.context["rows"]
            if item["child"].pk == self.child.pk
        )
        self.assertEqual(row["subscription"].pk, subscription.pk)
        self.assertEqual(row["sessions_left"], 0)
        self.assertEqual(row["sessions_used"], 3)
        self.assertContains(
            response,
            'data-session-usage data-used="3" data-total="8"',
        )
        self.assertContains(response, "3/8")
        self.assertNotContains(
            response,
            'data-session-usage data-used="8" data-total="8"',
        )

    def test_paid_additional_group_gets_own_renewal_row(self):
        today = timezone.localdate()
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        other_trainer = Trainer.objects.create(
            full_name="Тренер второй платной группы",
        )
        other_group = Group.objects.create(
            name="Вторая платная группа",
            trainer=other_trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )

        primary_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        additional_subscription = Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=4,
            price=Decimal("4000"),
            is_active=True,
        )
        Attendance.objects.create(
            child=self.child,
            date=end_date - timedelta(days=2),
            group_snapshot=self.group,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            child=self.child,
            date=end_date - timedelta(days=1),
            group_snapshot=other_group,
            status=Attendance.Status.PRESENT,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("payments"),
            {"month": end_date.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        rows = [
            row
            for row in response.context["rows"]
            if row["child"].pk == self.child.pk
        ]
        self.assertEqual(len(rows), 2)
        by_group = {row["group"].pk: row for row in rows}
        self.assertEqual(
            by_group[self.group.pk]["subscription"].pk,
            primary_subscription.pk,
        )
        self.assertEqual(
            by_group[other_group.pk]["subscription"].pk,
            additional_subscription.pk,
        )
        self.assertEqual(by_group[self.group.pk]["sessions_used"], 1)
        self.assertEqual(by_group[other_group.pk]["sessions_used"], 1)
        self.assertContains(response, self.group.name)
        self.assertContains(response, other_group.name)

    def test_prepayment_credit_is_not_duplicated_across_group_renewals(self):
        today = timezone.localdate()
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        other_group = Group.objects.create(
            name="Группа для общей предоплаты",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )
        primary_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        Payment.objects.create(
            child=self.child,
            subscription=primary_subscription,
            amount=Decimal("13000"),
            date=today,
            created_by=self.admin,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("payments"),
            {"month": end_date.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        rows = [
            row
            for row in response.context["rows"]
            if row["child"].pk == self.child.pk
        ]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sum((row["renewal_price"] for row in rows), Decimal("0")),
            Decimal("10000"),
        )
        self.assertEqual(
            sum((row["prepaid_credit"] for row in rows), Decimal("0")),
            Decimal("3000"),
        )
        self.assertEqual(
            sum((row["amount"] for row in rows), Decimal("0")),
            Decimal("7000"),
        )
        self.assertEqual(response.context["expected"], Decimal("7000"))

    def test_future_subscription_suppresses_only_its_group_renewal(self):
        today = timezone.localdate()
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        other_group = Group.objects.create(
            name="Группа без будущего продления",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        additional_subscription = Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=start_date,
            end_date=end_date,
            sessions_total=8,
            price=Decimal("4000"),
            is_active=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=31),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("payments"),
            {"month": end_date.strftime("%Y-%m")},
        )
        self.assertEqual(response.status_code, 200)

        rows = [
            row
            for row in response.context["rows"]
            if row["child"].pk == self.child.pk
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["group"].pk, other_group.pk)
        self.assertEqual(
            rows[0]["subscription"].pk,
            additional_subscription.pk,
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
        today = timezone.localdate()
        Subscription.objects.create(
            child=self.child,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )
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

    def test_ambiguous_multigroup_payment_is_not_misattributed(self):
        today = timezone.localdate()
        other_group = Group.objects.create(
            name="Группа второй оплаты",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("4000"),
            is_active=True,
        )

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
                "date": today.isoformat(),
            },
        )
        self.assertRedirects(response, reverse("payments"))

        payment = Payment.objects.get(
            child=self.child,
            amount=Decimal("1500"),
        )
        self.assertIsNone(payment.subscription)

    def test_payment_can_target_selected_group_subscription(self):
        today = timezone.localdate()
        other_group = Group.objects.create(
            name="Группа выбранной оплаты",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )
        primary_subscription = Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        target_subscription = Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("4000"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        page = self.client.get(reverse("payments"))
        self.assertContains(page, 'data-payment-subscription')
        self.assertContains(
            page,
            f'value="{target_subscription.pk}" data-child-id="{self.child.pk}"',
        )

        response = self.client.post(
            reverse("payments"),
            {
                "action": "payment",
                "child_id": self.child.pk,
                "subscription_id": target_subscription.pk,
                "amount": "1700",
                "date": today.isoformat(),
            },
        )
        self.assertRedirects(response, reverse("payments"))

        payment = Payment.objects.get(
            child=self.child,
            amount=Decimal("1700"),
        )
        self.assertEqual(payment.subscription, target_subscription)
        self.assertNotEqual(payment.subscription, primary_subscription)

    def test_child_card_highlights_all_current_group_subscriptions(self):
        today = timezone.localdate()
        other_group = Group.objects.create(
            name="Дополнительная группа карточки",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=other_group,
            requires_subscription=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=20),
            sessions_total=8,
            price=Decimal("5000"),
            is_active=True,
        )
        Subscription.objects.create(
            child=self.child,
            group=other_group,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=20),
            sessions_total=4,
            price=Decimal("3500"),
            is_active=True,
        )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)
        active_subscriptions = [
            subscription
            for subscription in response.context["subscriptions"]
            if subscription.pk in response.context["active_subscription_ids"]
        ]
        self.assertEqual(len(active_subscriptions), 2)
        self.assertEqual(
            {subscription.group_id for subscription in active_subscriptions},
            {self.group.pk, other_group.pk},
        )
        self.assertContains(response, self.group.name)
        self.assertContains(response, other_group.name)

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

    def test_trial_expires_after_thirty_days_without_payment(self):
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

    def test_attendance_colors_follow_subscription_state_not_mark_status(self):
        first_date = timezone.localdate() + timedelta(days=14)
        expired_date = first_date + timedelta(days=1)
        renewed_date = first_date + timedelta(days=2)

        for class_date in (first_date, expired_date, renewed_date):
            ScheduleSlot.objects.create(
                group=self.group,
                weekday=class_date.weekday(),
                start_time=time(18, 0),
            )

        Subscription.objects.create(
            child=self.child,
            start_date=first_date - timedelta(days=20),
            end_date=first_date,
            sessions_total=8,
            price=Decimal("5000"),
        )
        Subscription.objects.create(
            child=self.child,
            start_date=renewed_date,
            end_date=renewed_date + timedelta(days=30),
            sessions_total=8,
            price=Decimal("5000"),
        )
        Attendance.objects.create(
            child=self.child,
            date=first_date,
            status=Attendance.Status.ABSENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )
        Attendance.objects.create(
            child=self.child,
            date=renewed_date,
            status=Attendance.Status.PRESENT,
            group_snapshot=self.group,
            trainer_snapshot=self.trainer,
        )

        self.client.login(username="admin", password="TestPass123!")
        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": self.group.pk,
                "period": "custom",
                "date_from": first_date.isoformat(),
                "date_to": renewed_date.isoformat(),
                "ref_date": first_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        row = next(
            item
            for item in response.context["children_data"]
            if item["child"].pk == self.child.pk
        )
        entries = {
            entry["date"]: entry
            for entry in row["attendance_entries"]
        }
        self.assertEqual(
            entries[first_date]["subscription_state"],
            "active",
        )
        self.assertEqual(
            entries[expired_date]["subscription_state"],
            "expired",
        )
        self.assertEqual(
            entries[renewed_date]["subscription_state"],
            "renewed",
        )

        self.assertContains(response, 'data-subscription-state="active"')
        self.assertContains(response, 'data-subscription-state="expired"')
        self.assertContains(response, 'data-subscription-state="renewed"')
        self.assertContains(response, "bg-white border-slate-200")
        self.assertContains(response, "bg-red-50 border-red-300")
        self.assertContains(response, "bg-emerald-50 border-emerald-300")
        self.assertNotContains(
            response,
            "bg-red-100 text-red-700",
        )
        self.assertNotContains(
            response,
            "bg-emerald-100 text-emerald-700",
        )
        self.assertContains(response, "subscriptionStateClasses")
        self.assertContains(
            response,
            'data-attendance-choice="debt_present"',
        )
        self.assertContains(response, "requiresDebt")
        self.assertContains(response, "allow_debt")

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
        second_group = Group.objects.create(
            name="Чужая группа переноса",
            trainer=self.trainer,
        )
        ChildGroupMembership.objects.create(
            child=self.child,
            group=second_group,
            requires_subscription=True,
        )
        second_subscription = Subscription.objects.create(
            child=self.child,
            group=second_group,
            start_date=source_date - timedelta(days=10),
            end_date=source_date + timedelta(days=25),
            sessions_total=8,
            price=Decimal("4500"),
        )
        second_original_end = second_subscription.end_date
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
        second_subscription.refresh_from_db()
        self.assertEqual(
            second_subscription.end_date,
            second_original_end,
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

    def test_child_card_counts_absences_for_month_year_and_custom_period(self):
        selected_year = timezone.localdate().year - 1
        june_start = datetime(selected_year, 6, 1).date()
        june_second = datetime(selected_year, 6, 2).date()
        june_third = datetime(selected_year, 6, 3).date()
        july_start = datetime(selected_year, 7, 1).date()
        june_end = july_start - timedelta(days=1)

        for mark_date, status in (
            (june_start, Attendance.Status.ABSENT),
            (june_second, Attendance.Status.ABSENT),
            (june_third, Attendance.Status.SICK),
            (july_start, Attendance.Status.ABSENT),
        ):
            Attendance.objects.create(
                child=self.child,
                date=mark_date,
                group_snapshot=self.group,
                trainer_snapshot=self.trainer,
                status=status,
            )

        self.client.login(
            username="admin",
            password="TestPass123!",
        )

        month_page = self.client.get(
            reverse("child_card", args=[self.child.pk]),
            {
                "attendance_period": "month",
                "attendance_month": f"{selected_year}-06",
            },
        )
        self.assertEqual(month_page.status_code, 200)
        self.assertEqual(
            month_page.context["attendance_period_start"],
            june_start,
        )
        self.assertEqual(
            month_page.context["attendance_period_end"],
            june_end,
        )
        self.assertEqual(
            month_page.context["period_stats"]["absent"],
            2,
        )
        self.assertEqual(
            month_page.context["period_stats"]["sick"],
            1,
        )
        self.assertEqual(
            len(month_page.context["attendances"]),
            3,
        )
        self.assertContains(
            month_page,
            "data-child-attendance-period",
        )
        self.assertContains(
            month_page,
            'name="attendance_period"',
        )
        self.assertContains(
            month_page,
            'name="attendance_month"',
        )
        self.assertContains(
            month_page,
            'data-period-absences="2"',
        )
        self.assertContains(
            month_page,
            (
                f"{june_start:%d.%m.%Y} — "
                f"{june_end:%d.%m.%Y}"
            ),
        )
        self.assertContains(
            month_page,
            "Пропуски за период",
        )

        year_page = self.client.get(
            reverse("child_card", args=[self.child.pk]),
            {
                "attendance_period": "year",
                "attendance_year": str(selected_year),
            },
        )
        self.assertEqual(year_page.status_code, 200)
        self.assertEqual(
            year_page.context["attendance_period_start"],
            datetime(selected_year, 1, 1).date(),
        )
        self.assertEqual(
            year_page.context["attendance_period_end"],
            datetime(selected_year, 12, 31).date(),
        )
        self.assertEqual(
            year_page.context["period_stats"]["absent"],
            3,
        )
        self.assertEqual(
            year_page.context["period_stats"]["sick"],
            1,
        )
        self.assertEqual(
            len(year_page.context["attendances"]),
            4,
        )
        self.assertContains(
            year_page,
            'name="attendance_year"',
        )
        self.assertContains(
            year_page,
            'data-period-absences="3"',
        )

        custom_page = self.client.get(
            reverse("child_card", args=[self.child.pk]),
            {
                "attendance_period": "custom",
                "attendance_from": june_third.isoformat(),
                "attendance_to": june_second.isoformat(),
            },
        )
        self.assertEqual(custom_page.status_code, 200)
        self.assertEqual(
            custom_page.context["attendance_period_start"],
            june_second,
        )
        self.assertEqual(
            custom_page.context["attendance_period_end"],
            june_third,
        )
        self.assertEqual(
            custom_page.context["period_stats"]["absent"],
            1,
        )
        self.assertEqual(
            custom_page.context["period_stats"]["sick"],
            1,
        )
        self.assertEqual(
            len(custom_page.context["attendances"]),
            2,
        )
        self.assertContains(
            custom_page,
            'name="attendance_from"',
        )
        self.assertContains(
            custom_page,
            'name="attendance_to"',
        )
        self.assertContains(
            custom_page,
            'data-period-absences="1"',
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
