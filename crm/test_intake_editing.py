from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Lead, Newcomer


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
