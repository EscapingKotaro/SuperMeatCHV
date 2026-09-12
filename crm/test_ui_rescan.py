from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, RequestFactory
from django.urls import reverse

from .models import Child, Group, Trainer, Notification, Payment, Newcomer


class UIRescanTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rescan", is_staff=True)
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Группа", trainer=Trainer.objects.create(full_name="Тренер"))
        self.child = Child.objects.create(first_name="Анна", last_name="Петрова", birth_year=2016, group=self.group)

    def test_notifications_pagination_and_read_scope(self):
        Notification.objects.bulk_create([Notification(recipient=self.user, kind="task_created", message=f"Событие {i}") for i in range(55)])
        first = self.client.get(reverse("notifications"))
        second = self.client.get(reverse("notifications"), {"page": 2})
        self.assertEqual(len(first.context["event_notifications"]), 50)
        self.assertEqual(len(second.context["event_notifications"]), 5)
        shown = [item.pk for item in second.context["event_notifications"]]
        other = get_user_model().objects.create_user(username="other-notifications")
        foreign = Notification.objects.create(recipient=other, kind="task_created", message="Чужое")
        response = self.client.post(reverse("notifications") + "?page=2", {
            "action": "mark_page_read", "notification_ids": [*shown, foreign.pk],
        })
        self.assertRedirects(response, reverse("notifications") + "?page=2", fetch_redirect_response=False)
        self.assertEqual(Notification.objects.filter(recipient=self.user, read_at__isnull=False).count(), 5)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.read_at)

    def test_trial_missing_date_opens_correction(self):
        newcomer = Newcomer.objects.create(full_name="Новичок")
        response = self.client.post(reverse("notifications"), {"action": "confirm_trial", "newcomer_id": newcomer.pk})
        self.assertRedirects(response, reverse("newcomers") + f"?edit={newcomer.pk}", fetch_redirect_response=False)
        newcomer.refresh_from_db()
        self.assertFalse(newcomer.attended)

    def test_document_error_preserves_dates_and_comment(self):
        self.child.certificate = "existing.png"
        self.child.save(update_fields=["certificate"])
        response = self.client.post(reverse("child_certificate_manage", args=[self.child.pk]), {
            "action": "upload", "kind": "certificate", "valid_from": "2026-11-01",
            "valid_until": "2026-10-01", "note": "Уточняем срок",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Уточняем срок")
        self.assertContains(response, 'value="2026-11-01"')
        self.assertContains(response, "Старый файл не изменён")
        self.child.refresh_from_db()
        self.assertEqual(self.child.certificate.name, "existing.png")

    def test_missing_stored_document_returns_to_card(self):
        self.child.certificate = "missing.png"
        self.child.save(update_fields=["certificate"])
        with patch("django.core.files.storage.FileSystemStorage.open", side_effect=FileNotFoundError):
            response = self.client.get(reverse("child_document", args=[self.child.pk, "certificate"]))
        self.assertRedirects(response, reverse("child_card", args=[self.child.pk]), fetch_redirect_response=False)

    def test_payment_history_displays_kopecks_and_unallocated_payment(self):
        Payment.objects.create(child=self.child, amount=Decimal("12.34"), date=date(2026, 9, 1))
        response = self.client.get(reverse("payment_history"), {"month": "2026-09"})
        self.assertContains(response, "12,34", count=2)
        self.assertContains(response, "Без привязки к абонементу")

    def test_legacy_staff_templates_have_live_destination(self):
        request = RequestFactory().get("/")
        request.user = self.user
        for name in ["user_list", "user_form", "change_password"]:
            html = render_to_string(f"crm/users/{name}.html", request=request)
            self.assertIn("Управление сотрудниками перенесено", html)
            self.assertIn(reverse("profile"), html)

    def test_profile_and_scores_opt_into_draft_protection(self):
        from .models import Competition
        competition = Competition.objects.create(name="Турнир", date=date(2026, 9, 1))
        response = self.client.get(reverse("profile"))
        self.assertContains(response, 'method="post" data-guard-draft', count=3)
        response = self.client.get(reverse("competitions"), {"competition": competition.pk})
        self.assertContains(response, 'id="scores-form"\n    method="post" data-guard-draft')

    def test_cancelled_subscription_is_read_only_and_cannot_be_saved(self):
        from django.utils import timezone
        from .models import Subscription
        sub = Subscription.objects.create(child=self.child, group=self.group, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), price=100, is_active=False, cancelled_at=timezone.now())
        url = reverse("payments") + f"?edit_subscription={sub.pk}"
        response = self.client.get(url)
        self.assertContains(response, "Оформить новый абонемент")
        self.assertTrue(all(field.disabled for field in response.context["subscription_form"].fields.values()))
        response = self.client.post(url, {"action": "save_subscription", "subscription-price": "999", "subscription-is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["subscription_form"].errors)
        sub.refresh_from_db()
        self.assertEqual(sub.price, 100)
        self.assertFalse(sub.is_active)

    def test_legacy_task_notification_opens_its_month(self):
        from .models import ManagerTask
        task = ManagerTask.objects.create(title="Задача в другом месяце", due_date=date(2026, 12, 15), assignee=self.user, created_by=self.user)
        Notification.objects.create(recipient=self.user, task=task, kind="task_created", message="Старая ссылка", url="")
        response = self.client.get(reverse("notifications"))
        self.assertContains(response, '?start=2026-12-01&day=2026-12-15', html=False)
