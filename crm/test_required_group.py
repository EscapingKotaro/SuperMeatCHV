from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import ChildForm
from .models import Child, Group, Newcomer, Trainer


class RequiredChildGroupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "group-admin",
            password="TestPass123!",
            is_staff=True,
        )
        self.client.login(
            username="group-admin",
            password="TestPass123!",
        )

        self.trainer = Trainer.objects.create(
            full_name="Тестовый тренер",
        )
        self.group = Group.objects.create(
            name="Тестовая группа",
            trainer=self.trainer,
        )

    def child_form_data(self, group=""):
        return {
            "last_name": "Иванова",
            "first_name": "Анна",
            "patronymic": "",
            "birth_date": "",
            "birth_year": "2016",
            "address": "",
            "parent_name": "",
            "parent_phone": "",
            "certificate_ok": "",
            "certificate_note": "",
            "group": group,
            "status": Child.Status.ACTIVE,
            "trial_from": "",
            "discount_percent": "0",
            "note": "",
        }

    def test_child_form_requires_group(self):
        form = ChildForm(
            data=self.child_form_data(),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("group", form.errors)
        self.assertTrue(form.fields["group"].required)

    def test_child_form_accepts_selected_group(self):
        form = ChildForm(
            data=self.child_form_data(
                str(self.group.pk),
            ),
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_newcomer_without_group_cannot_be_converted(self):
        newcomer = Newcomer.objects.create(
            full_name="Петров Иван",
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
            reverse("newcomers"),
        )

        newcomer.refresh_from_db()
        self.assertIsNone(newcomer.child_id)
        self.assertEqual(Child.objects.count(), 0)

    def test_newcomer_with_group_is_converted(self):
        newcomer = Newcomer.objects.create(
            full_name="Петров Иван",
            group=self.group,
        )

        response = self.client.post(
            reverse("newcomers"),
            {
                "action": "convert",
                "newcomer_id": newcomer.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        newcomer.refresh_from_db()
        self.assertIsNotNone(newcomer.child_id)
        self.assertEqual(
            newcomer.child.group_id,
            self.group.pk,
        )
