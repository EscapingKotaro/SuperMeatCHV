from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Group, Lead, Newcomer, Trainer


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
        self.assertEqual(lead.status, Lead.Status.CONTACTED)
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
            "Создать карточку спортсмена",
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
        self.assertNotContains(response, "Назначить пробное")

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
        self.assertContains(response, "Назначить пробное")

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
            'data-filter="cancelled"',
        ):
            self.assertContains(response, marker)
        self.assertContains(response, 'data-birth-year="2015"')
        self.assertContains(response, 'name="field" value="attended"')
        self.assertContains(response, 'name="field" value="lesson_cancelled"')
        self.assertNotContains(response, 'name="field" value="paid"')
        self.assertContains(response, "matchesAge(row, v.age)")
        self.assertContains(response, "row.dataset.paid === v.paid")

    def test_newcomer_quick_flags_are_mutually_exclusive_and_paid_is_read_only(self):
        newcomer = Newcomer.objects.create(
            full_name="Быстрая отметка",
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
