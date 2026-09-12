from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, AttendanceChargeRevision, Child, Group, Trainer
from .forms import CompetitionEntryForm, CampEventForm


class FinalWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="final-boss", password="test")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Группа", trainer=Trainer.objects.create(full_name="Тренер"))
        self.child = Child.objects.create(first_name="Анна", last_name="Петрова", birth_year=2016, group=self.group)

    def test_lookup_limits_and_preserves_subscription_metadata(self):
        for index in range(34):
            Child.objects.create(first_name="Анна", last_name=f"Петрова{index}", birth_year=2016, group=self.group)
        data = self.client.get(reverse("athlete_lookup"), {"q": "петрова", "scope": "subscription"}).json()
        self.assertEqual(len(data["results"]), 30)
        self.assertTrue(data["more"])
        self.assertIn("data-group-ids", data["results"][0]["attrs"])
        self.assertIn("data-discount-percent", data["results"][0]["attrs"])
        self.assertEqual(self.client.get(reverse("athlete_lookup"), {"q": "а"}).json()["results"], [])

    def test_render_only_selected_children_but_validate_full_queryset(self):
        another = Child.objects.create(first_name="Ольга", last_name="Иванова", birth_year=2016, group=self.group)
        form = CompetitionEntryForm(initial={"child": self.child.pk})
        html = str(form["child"])
        self.assertIn(str(self.child), html)
        self.assertNotIn(str(another), html)
        bound = CompetitionEntryForm(data={"child": another.pk, "category": "", "rank": "", "place": ""})
        self.assertTrue(bound.is_valid(), bound.errors)
        camp = CampEventForm(initial={"children": [self.child.pk, another.pk]})
        self.assertIn(str(self.child), str(camp["children"]))
        self.assertIn(str(another), str(camp["children"]))

    def test_lookup_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("athlete_lookup"), {"q": "Петрова"}).status_code, 302)

    def test_charge_correction_updates_balance_not_revenue_and_preserves_history(self):
        mark = Attendance.objects.create(child=self.child, date=timezone.localdate(), status="present", charge_amount=100)
        url = reverse("trial_management", args=[self.child.pk])
        page = self.client.get(url)
        data = {"action": "charge", "attendance": mark.pk, "amount": "25", "reason": "Ошибочно начислена сумма",
            "version": page.context["charge_form"].initial["version"]}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.child.financial_summary()["attendance_charges"], 25)
        self.assertFalse(self.child.payments.exists())
        row = AttendanceChargeRevision.objects.get()
        self.assertEqual(row.previous_amount, 100)
        self.assertEqual(row.new_amount, 25)
        self.assertTrue(self.client.post(url, data).context["charge_form"].errors)
        original_id = mark.pk
        mark.delete()
        row.refresh_from_db()
        self.assertIsNone(row.attendance_id)
        self.assertEqual(row.attendance_number, original_id)

    def test_charge_cannot_be_negative_or_belong_to_other_child(self):
        mark = Attendance.objects.create(child=self.child, date=timezone.localdate(), status="present", charge_amount=100)
        url = reverse("trial_management", args=[self.child.pk])
        page = self.client.get(url)
        response = self.client.post(url, {"action": "charge", "attendance": mark.pk, "amount": "-5", "reason": "Неверное начисление", "version": page.context["charge_form"].initial["version"]})
        self.assertIn("amount", response.context["charge_form"].errors)
        self.assertFalse(AttendanceChargeRevision.objects.exists())
