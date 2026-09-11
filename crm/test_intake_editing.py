from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ChildForm
from .models import Child, Group, Lead, Newcomer, Payment, Trainer


class IntakeEditRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "intake-admin",
            password="TestPass123!",
            is_staff=True,
        )
        self.client.login(
            username="intake-admin",
            password="TestPass123!",
        )

    def test_stale_application_query_cannot_overwrite_old_lead(self):
        old = Lead.objects.create(
            full_name="Старая заявка",
            status=Lead.Status.NEW,
        )

        response = self.client.post(
            f"{reverse('applications')}?edit={old.pk}",
            {
                "action": "save",
                "form_mode": "create",
                "editing_id": "",
                "full_name": "Новая заявка",
                "status": Lead.Status.NEW,
            },
        )

        self.assertRedirects(response, reverse("applications"))
        old.refresh_from_db()
        self.assertEqual(old.full_name, "Старая заявка")
        self.assertTrue(
            Lead.objects.filter(full_name="Новая заявка").exists()
        )
        self.assertEqual(Lead.objects.count(), 2)

    def test_application_edit_uses_explicit_editing_id(self):
        lead = Lead.objects.create(
            full_name="До редактирования",
            status=Lead.Status.NEW,
        )

        response = self.client.post(
            reverse("applications"),
            {
                "action": "save",
                "form_mode": "edit",
                "editing_id": str(lead.pk),
                "full_name": "После редактирования",
                "status": Lead.Status.CONTACTED,
            },
        )

        self.assertRedirects(response, reverse("applications"))
        lead.refresh_from_db()
        self.assertEqual(lead.full_name, "После редактирования")
        self.assertEqual(lead.status, Lead.Status.NEW)
        self.assertEqual(Lead.objects.count(), 1)

    def test_stale_newcomer_query_cannot_overwrite_old_record(self):
        old = Newcomer.objects.create(
            full_name="Старый новичок",
        )

        response = self.client.post(
            f"{reverse('newcomers')}?edit={old.pk}",
            {
                "action": "save",
                "form_mode": "create",
                "editing_id": "",
                "full_name": "Новый новичок",
            },
        )

        self.assertRedirects(response, reverse("newcomers"))
        old.refresh_from_db()
        self.assertEqual(old.full_name, "Старый новичок")
        self.assertTrue(
            Newcomer.objects.filter(full_name="Новый новичок").exists()
        )
        self.assertEqual(Newcomer.objects.count(), 2)

    def test_newcomer_edit_uses_explicit_editing_id(self):
        newcomer = Newcomer.objects.create(
            full_name="До редактирования",
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "save",
                "form_mode": "edit",
                "editing_id": str(newcomer.pk),
                "full_name": "После редактирования",
                "attended": "on",
            },
        )

        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertEqual(newcomer.full_name, "После редактирования")
        self.assertTrue(newcomer.attended)
        self.assertEqual(Newcomer.objects.count(), 1)

    def test_legacy_query_edit_remains_supported(self):
        lead = Lead.objects.create(
            full_name="Старая заявка",
            status=Lead.Status.NEW,
        )
        newcomer = Newcomer.objects.create(
            full_name="Старый новичок",
        )

        lead_response = self.client.post(
            f"{reverse('applications')}?edit={lead.pk}",
            {
                "full_name": "Обновлённая заявка",
                "status": Lead.Status.CONTACTED,
            },
        )
        newcomer_response = self.client.post(
            f"{reverse('newcomers')}?edit={newcomer.pk}",
            {
                "full_name": "Обновлённый новичок",
            },
        )

        self.assertRedirects(
            lead_response,
            reverse("applications"),
        )
        self.assertRedirects(
            newcomer_response,
            reverse("newcomers"),
        )

        lead.refresh_from_db()
        newcomer.refresh_from_db()

        self.assertEqual(
            lead.full_name,
            "Обновлённая заявка",
        )
        self.assertEqual(
            newcomer.full_name,
            "Обновлённый новичок",
        )

    def test_create_buttons_use_clean_create_urls(self):
        applications = self.client.get(reverse("applications"))
        newcomers = self.client.get(reverse("newcomers"))

        self.assertContains(
            applications,
            f'{reverse("applications")}?create=1',
        )
        self.assertContains(
            newcomers,
            f'{reverse("newcomers")}?create=1',
        )

    def test_edit_forms_keep_target_and_clean_cancel_url(self):
        lead = Lead.objects.create(
            full_name="Редактируемая заявка",
            status=Lead.Status.NEW,
        )
        newcomer = Newcomer.objects.create(
            full_name="Редактируемый новичок",
        )

        applications = self.client.get(
            f"{reverse('applications')}?edit={lead.pk}",
        )
        newcomers = self.client.get(
            f"{reverse('newcomers')}?edit={newcomer.pk}",
        )

        self.assertContains(
            applications,
            f'name="editing_id" value="{lead.pk}"',
        )
        self.assertContains(
            applications,
            f'href="{reverse("applications")}"',
        )
        self.assertContains(
            newcomers,
            f'name="editing_id" value="{newcomer.pk}"',
        )
        self.assertContains(
            newcomers,
            f'href="{reverse("newcomers")}"',
        )
        self.assertContains(
            newcomers,
            "Нужны дата и группа",
        )

    def test_applications_show_workflow_state_without_ad_row_highlight(self):
        lead = Lead.objects.create(
            full_name="Рекламная заявка",
            source="VK Реклама",
            status=Lead.Status.QUALIFIED,
            imported_from_ad=True,
        )
        newcomer = Newcomer.objects.create(
            lead=lead,
            full_name=lead.full_name,
            attended=True,
        )

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "из рекламы")
        self.assertContains(response, "Пробное посещено")
        self.assertContains(
            response,
            f'{reverse("newcomers")}?edit={newcomer.pk}',
        )
        self.assertNotContains(response, "bg-blue-50/70")
        self.assertNotContains(response, "Они выделены синим")
        self.assertNotContains(response, "В новички")
        self.assertNotContains(response, ">В пробные<", html=True)

    def test_applications_have_open_closed_all_workflow_filter(self):
        Lead.objects.create(
            full_name="Открытая заявка",
            status=Lead.Status.NEW,
        )
        Lead.objects.create(
            full_name="Закрытая заявка",
            status=Lead.Status.LOST,
        )

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-lead-filter="open"')
        self.assertContains(response, 'data-lead-filter="closed"')
        self.assertContains(response, 'data-lead-filter="all"')
        self.assertContains(response, 'data-lead-state="open"')
        self.assertContains(response, 'data-lead-state="closed"')
        self.assertContains(response, "const defaultLeadState = 'open';")
        self.assertContains(
            response,
            "state === 'all' || row.dataset.leadState === state",
        )
        self.assertContains(response, "В пробные")
        self.assertContains(response, "Путь клиента")
        self.assertContains(response, "Завершённые")

    def test_applications_have_detailed_filters_and_application_date(self):
        trainer = Trainer.objects.create(
            full_name="Тренер фильтра",
        )
        Lead.objects.create(
            full_name="Фильтруемая заявка",
            birth_date=date(2015, 4, 10),
            trainer=trainer,
            status=Lead.Status.CONTACTED,
        )

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>Дата заявки</th>", html=True)
        self.assertContains(response, 'data-lead-status-filter')
        self.assertContains(response, 'data-lead-trainer-filter')
        self.assertContains(response, 'data-lead-date-from')
        self.assertContains(response, 'data-lead-date-to')
        self.assertContains(response, 'data-lead-age-filter')
        self.assertContains(response, 'data-lead-status="contacted"')
        self.assertContains(
            response,
            f'data-lead-trainer-id="{trainer.pk}"',
        )
        self.assertContains(response, 'data-lead-birth-year="2015"')
        self.assertContains(response, 'data-lead-date="')
        self.assertContains(response, "matchesDetailedFilters")
        self.assertContains(response, "row.dataset.leadDate >= dateFrom")
        self.assertContains(response, "row.dataset.leadDate <= dateTo")
        self.assertContains(response, "matchesAge(row, age)")
        self.assertContains(response, 'colspan="10"')


    def test_application_form_calculates_age_from_birth_date_and_gates_groups_by_trainer(self):
        trainer = Trainer.objects.create(full_name="Основной тренер")
        other_trainer = Trainer.objects.create(full_name="Другой тренер")
        group = Group.objects.create(name="Группа тренера", trainer=trainer)
        other_group = Group.objects.create(name="Чужая группа", trainer=other_trainer)

        response = self.client.get(f"{reverse('applications')}?create=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="birth_date"')
        self.assertNotContains(response, 'name="age_text"')
        self.assertNotIn("status", response.context["form"].fields)
        self.assertContains(response, "Возраст рассчитывается автоматически")
        self.assertContains(response, "data-lead-age-preview")
        self.assertContains(response, f'data-trainer-id="{trainer.pk}"')
        self.assertContains(response, f'data-trainer-id="{other_trainer.pk}"')
        self.assertContains(response, "function updateAgePreview()")
        self.assertContains(response, "function syncGroups()")
        self.assertContains(response, "group.disabled = !trainerId")
        self.assertContains(response, "option.dataset.trainerId === trainerId")

        wrong_group = self.client.post(
            reverse("applications"),
            {
                "action": "save",
                "form_mode": "create",
                "editing_id": "",
                "full_name": "Несовпадающая группа",
                "birth_date": "2016-04-15",
                "trainer": str(trainer.pk),
                "group": str(other_group.pk),
                "status": Lead.Status.NEW,
            },
        )
        self.assertEqual(wrong_group.status_code, 200)
        self.assertContains(wrong_group, "Выберите группу выбранного тренера")
        self.assertFalse(Lead.objects.filter(full_name="Несовпадающая группа").exists())

        without_trainer = self.client.post(
            reverse("applications"),
            {
                "action": "save",
                "form_mode": "create",
                "editing_id": "",
                "full_name": "Группа без тренера",
                "birth_date": "2016-04-15",
                "group": str(group.pk),
                "status": Lead.Status.NEW,
            },
        )
        self.assertEqual(without_trainer.status_code, 200)
        self.assertContains(without_trainer, "Сначала выберите тренера")
        self.assertFalse(Lead.objects.filter(full_name="Группа без тренера").exists())

        valid = self.client.post(
            reverse("applications"),
            {
                "action": "save",
                "form_mode": "create",
                "editing_id": "",
                "full_name": "Корректная заявка",
                "birth_date": "2016-04-15",
                "trainer": str(trainer.pk),
                "group": str(group.pk),
                "status": Lead.Status.NEW,
            },
        )
        self.assertRedirects(valid, reverse("applications"))
        lead = Lead.objects.get(full_name="Корректная заявка")
        self.assertEqual(lead.birth_date, date(2016, 4, 15))
        self.assertEqual(lead.trainer, trainer)
        self.assertEqual(lead.group, group)

    def test_application_edit_keeps_locked_trial_fields_compatible_with_group_gate(self):
        trainer = Trainer.objects.create(full_name="Тренер пробного")
        group = Group.objects.create(name="Группа пробного", trainer=trainer)
        lead = Lead.objects.create(
            full_name="Заявка с пробным",
            trainer=trainer,
            group=group,
            status=Lead.Status.QUALIFIED,
        )
        Newcomer.objects.create(
            lead=lead,
            full_name=lead.full_name,
            trainer=trainer,
            group=group,
        )

        response = self.client.get(f"{reverse('applications')}?edit={lead.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="trainer"', count=1)
        self.assertContains(response, 'name="group"', count=1)
        self.assertContains(response, "Пробное изменяется в разделе «Новички»")
        self.assertContains(response, "if (!trainer || !group || trainer.disabled) return;")

    def test_application_status_is_inline_and_uses_spec_colors(self):
        for name, status in (
            ("Новая", Lead.Status.NEW),
            ("Рабочая", Lead.Status.CONTACTED),
            ("Пробная", Lead.Status.QUALIFIED),
            ("Закрытая", Lead.Status.LOST),
        ):
            Lead.objects.create(full_name=name, status=status)

        response = self.client.get(f"{reverse('applications')}?state=all")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-lead-status-form')
        self.assertContains(response, 'name="action" value="quick_status"')
        for label in ("Новая заявка", "В работе", "Пробное", "Оплатил", "Закрыта"):
            self.assertContains(response, label)
        for visual in ("new", "work", "trial", "closed"):
            self.assertContains(response, f'data-lead-visual="{visual}"')
        for color in (
            "border-amber-400 bg-amber-50",
            "border-emerald-600 bg-emerald-100",
            "border-red-500 bg-red-50",
        ):
            self.assertContains(response, color)

    def test_application_quick_status_and_paid_state_follow_real_payment(self):
        trainer = Trainer.objects.create(full_name="Тренер оплаты")
        group = Group.objects.create(name="Группа оплаты", trainer=trainer)
        child = Child.objects.create(
            last_name="Платёжный", first_name="Ребёнок", birth_year=2016, group=group,
        )
        lead = Lead.objects.create(
            full_name="Быстрый статус", status=Lead.Status.NEW,
            trainer=trainer, group=group, child=child,
        )
        Newcomer.objects.create(
            lead=lead, full_name=lead.full_name, trainer=trainer, group=group, child=child,
        )
        target = f"{reverse('applications')}?state=all&status=contacted"

        response = self.client.post(target, {
            "action": "quick_status", "lead_id": str(lead.pk),
            "status": Lead.Status.CONTACTED,
        })
        self.assertRedirects(response, target)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.CONTACTED)

        response = self.client.post(reverse("applications"), {
            "action": "quick_status", "lead_id": str(lead.pk), "status": "paid",
        })
        self.assertRedirects(response, reverse("applications"))
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.CONTACTED)

        payment = Payment.objects.create(child=child, amount="5000")
        paid_page = self.client.get(f"{reverse('applications')}?state=all")
        self.assertContains(paid_page, 'data-lead-status="paid"')
        self.assertContains(paid_page, 'data-lead-state="closed"')
        self.assertContains(paid_page, 'data-lead-visual="paid"')
        self.assertContains(paid_page, "border-sky-500 bg-sky-100")
        self.assertContains(paid_page, 'data-paid-status-source')

        closed = self.client.post(reverse("applications"), {
            "action": "close_lead",
            "lead_id": str(lead.pk),
            "closed_until": date.today().isoformat(),
            "closed_reason": "Regression: вернуться к оплаченной заявке",
        })
        self.assertRedirects(closed, reverse("applications"))
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.LOST)
        self.assertEqual(lead.closed_until, date.today())
        self.assertEqual(
            lead.closed_reason,
            "Regression: вернуться к оплаченной заявке",
        )

        reopened = self.client.post(reverse("applications"), {
            "action": "quick_status", "lead_id": str(lead.pk), "status": "paid",
        })
        self.assertRedirects(reopened, reverse("applications"))
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.QUALIFIED)

        payment.delete()
        trial_page = self.client.get(f"{reverse('applications')}?state=all")
        self.assertContains(trial_page, 'data-lead-status="qualified"')
        self.assertContains(trial_page, 'data-lead-visual="trial"')

    def test_trial_payment_assigns_working_group_and_keeps_trial_history(self):
        trial_trainer = Trainer.objects.create(
            full_name="Тренер пробного платежа",
        )
        working_trainer = Trainer.objects.create(
            full_name="Тренер рабочей группы",
        )
        trial_group = Group.objects.create(
            name="Пробная группа платежа",
            trainer=trial_trainer,
        )
        working_group = Group.objects.create(
            name="Рабочая группа платежа",
            trainer=working_trainer,
        )
        child = Child.objects.create(
            last_name="Оплатил",
            first_name="Пробник",
            birth_year=2016,
            group=trial_group,
            status=Child.Status.TRIAL,
            trial_from=date.today(),
        )
        newcomer = Newcomer.objects.create(
            full_name="Оплатил Пробник",
            child=child,
            group=trial_group,
            trainer=trial_trainer,
            attended=True,
        )

        page = self.client.get(reverse("payments"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "data-payment-working-group")
        self.assertContains(page, 'data-child-status="trial"')
        self.assertContains(page, "Рабочая группа после оплаты")

        blocked = self.client.post(
            reverse("payments"),
            {
                "action": "payment",
                "child_id": str(child.pk),
                "subscription_id": "",
                "amount": "1500",
                "date": date.today().isoformat(),
                "working_group_id": "",
            },
        )
        self.assertEqual(blocked.status_code, 302)
        self.assertFalse(Payment.objects.filter(child=child).exists())

        paid = self.client.post(
            reverse("payments"),
            {
                "action": "payment",
                "child_id": str(child.pk),
                "subscription_id": "",
                "amount": "1500",
                "date": date.today().isoformat(),
                "working_group_id": str(working_group.pk),
            },
        )
        self.assertIn(paid.status_code, (200, 302))

        child.refresh_from_db()
        newcomer.refresh_from_db()

        self.assertEqual(child.status, Child.Status.ACTIVE)
        self.assertEqual(child.group, working_group)
        self.assertTrue(newcomer.paid)
        self.assertEqual(newcomer.group, trial_group)
        self.assertEqual(newcomer.trainer, trial_trainer)
        self.assertTrue(
            Payment.objects.filter(
                child=child,
                amount="1500",
            ).exists(),
        )

        trial_membership = child.group_memberships.get(group=trial_group)
        working_membership = child.group_memberships.get(group=working_group)
        self.assertFalse(trial_membership.is_primary)
        self.assertIsNotNone(trial_membership.archived_at)
        self.assertTrue(working_membership.is_primary)
        self.assertIsNone(working_membership.archived_at)

    def test_newcomers_have_filters_and_inline_operational_flags(self):
        trainer = Trainer.objects.create(full_name="Тренер пробников")
        group = Group.objects.create(name="Пробная группа", trainer=trainer)
        Newcomer.objects.create(
            full_name="Фильтруемый новичок",
            birth_date=date(2015, 6, 15),
            trainer=trainer,
            group=group,
            attended=True,
        )

        response = self.client.get(reverse("newcomers"))

        self.assertEqual(response.status_code, 200)
        for marker in (
            'data-filter="q"',
            'data-filter="trainer"',
            'data-filter="group"',
            'data-filter="age"',
            'data-filter="from"',
            'data-filter="to"',
            'data-filter="attended"',
            'data-filter="paid"',
            'data-filter="documents"',
            'data-filter="not_liked"',
            'data-filter="cancelled"',
        ):
            self.assertContains(response, marker)
        self.assertContains(response, 'data-birth-year="2015"')
        self.assertContains(response, 'name="field" value="attended"')
        self.assertContains(response, 'name="field" value="documents_collected"')
        self.assertContains(response, 'name="field" value="trial_not_liked"')
        self.assertContains(response, 'name="field" value="lesson_cancelled"')
        self.assertNotContains(response, 'name="field" value="paid"')
        self.assertContains(response, 'data-documents="0"')
        self.assertContains(response, 'data-not-liked="0"')
        self.assertContains(response, "matchesAge(row, v.age)")
        self.assertContains(response, "row.dataset.paid === v.paid")
        self.assertContains(response, "row.dataset.documents === v.documents")
        self.assertContains(response, "row.dataset.notLiked === v.not_liked")

    def test_newcomer_quick_flags_are_mutually_exclusive_and_paid_is_read_only(self):
        newcomer = Newcomer.objects.create(
            full_name="Быстрая отметка",
            trial_at=timezone.now(),
            lesson_cancelled=True,
        )

        for field, expected_attended, expected_cancelled in (
            ("attended", True, False),
            ("lesson_cancelled", False, True),
        ):
            response = self.client.post(
                reverse("newcomers"),
                {
                    "action": "quick_flag",
                    "newcomer_id": str(newcomer.pk),
                    "field": field,
                    "value": "1",
                },
            )
            self.assertRedirects(response, reverse("newcomers"))
            newcomer.refresh_from_db()
            self.assertEqual(newcomer.attended, expected_attended)
            self.assertEqual(newcomer.lesson_cancelled, expected_cancelled)

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "paid",
                "value": "1",
            },
        )
        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertFalse(newcomer.paid)
        self.assertFalse(newcomer.has_paid)

    def test_newcomer_documents_and_not_liked_flags_keep_trial_state_consistent(self):
        newcomer = Newcomer.objects.create(
            full_name="Результат пробного",
            trial_at=timezone.now(),
            lesson_cancelled=True,
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "documents_collected",
                "value": "1",
            },
        )
        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertTrue(newcomer.documents_collected)
        self.assertTrue(newcomer.lesson_cancelled)

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "trial_not_liked",
                "value": "1",
            },
        )
        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertTrue(newcomer.trial_not_liked)
        self.assertTrue(newcomer.attended)
        self.assertFalse(newcomer.lesson_cancelled)

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "attended",
                "value": "0",
            },
        )
        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertFalse(newcomer.attended)
        self.assertFalse(newcomer.trial_not_liked)

        newcomer.attended = True
        newcomer.trial_not_liked = True
        newcomer.save(update_fields=["attended", "trial_not_liked"])
        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "lesson_cancelled",
                "value": "1",
            },
        )
        self.assertRedirects(response, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertTrue(newcomer.lesson_cancelled)
        self.assertFalse(newcomer.attended)
        self.assertFalse(newcomer.trial_not_liked)

        normalized = Newcomer.objects.create(
            full_name="Нормализация пробного",
            attended=True,
            lesson_cancelled=True,
            trial_not_liked=True,
        )
        self.assertTrue(normalized.lesson_cancelled)
        self.assertFalse(normalized.attended)
        self.assertFalse(normalized.trial_not_liked)


    def test_trial_status_requires_newcomer_and_action_opens_trial_record(self):
        lead = Lead.objects.create(
            full_name="Переход в пробные",
            status=Lead.Status.NEW,
        )

        blocked = self.client.post(
            reverse("applications"),
            {
                "action": "quick_status",
                "lead_id": str(lead.pk),
                "status": Lead.Status.QUALIFIED,
            },
        )
        self.assertRedirects(blocked, reverse("applications"))
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.NEW)
        self.assertFalse(lead.newcomers.exists())

        moved = self.client.post(
            reverse("applications"),
            {
                "action": "create_newcomer",
                "lead_id": str(lead.pk),
                "open_newcomer": "1",
            },
        )
        newcomer = lead.newcomers.get()
        self.assertRedirects(
            moved,
            f"{reverse('newcomers')}?edit={newcomer.pk}",
        )
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.QUALIFIED)

    def test_trial_result_flags_require_scheduled_trial(self):
        newcomer = Newcomer.objects.create(
            full_name="Пробное без даты",
        )

        blocked = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "attended",
                "value": "1",
            },
        )
        self.assertRedirects(blocked, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertFalse(newcomer.attended)

        documents = self.client.post(
            reverse("newcomers"),
            {
                "action": "quick_flag",
                "newcomer_id": str(newcomer.pk),
                "field": "documents_collected",
                "value": "1",
            },
        )
        self.assertRedirects(documents, reverse("newcomers"))
        newcomer.refresh_from_db()
        self.assertTrue(newcomer.documents_collected)

    def test_ui_conversion_uses_age_and_trial_date_and_opens_card(self):
        trainer = Trainer.objects.create(full_name="Тренер конверсии")
        group = Group.objects.create(name="Группа конверсии", trainer=trainer)
        trial_at = timezone.now()
        newcomer = Newcomer.objects.create(
            full_name="Иванов Пётр",
            age_text="10 лет",
            trial_at=trial_at,
            trainer=trainer,
            group=group,
            attended=True,
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "convert",
                "newcomer_id": str(newcomer.pk),
                "return_to_card": "1",
            },
        )

        newcomer.refresh_from_db()
        child = newcomer.child
        self.assertRedirects(
            response,
            reverse("child_card", args=[child.pk]),
        )
        self.assertEqual(
            child.birth_year,
            timezone.localdate().year - 10,
        )
        self.assertEqual(
            child.trial_from,
            timezone.localtime(trial_at).date(),
        )
        self.assertEqual(child.status, Child.Status.TRIAL)

    def test_intake_ui_and_dispensary_field_explain_real_meaning(self):
        applications = self.client.get(reverse("applications"))
        newcomers = self.client.get(reverse("newcomers"))

        self.assertContains(applications, "data-intake-workflow")
        self.assertContains(newcomers, "data-intake-workflow")
        self.assertContains(newcomers, "Добавить пробное")

        field = ChildForm().fields["dispensary_region"]
        self.assertEqual(field.label, "Регион диспансеризации")
        self.assertIn(
            (Child.DispensaryRegion.OTHER, "Другой регион"),
            list(field.choices),
        )
