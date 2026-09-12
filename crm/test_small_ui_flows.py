from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.test import RequestFactory
from django.utils import timezone
from datetime import time, timedelta

from .models import Attendance, AttendanceReason, Child, Group, ScheduleSlot, Trainer, Subscription, Tariff
from .certificate_views import ChildDocumentUploadForm
from .navigation import list_url


class SmallUIFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ui-flow", password="TestPass123!", is_staff=True,
        )

    def test_empty_attendance_offers_group_setup(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("group_list") + "?create=1")
        self.assertNotContains(response, 'id="trial-modal"')

    def test_login_keeps_destination_after_wrong_password(self):
        destination = reverse("clients") + "?state=inactive"
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "wrong",
            "next": destination,
        })
        self.assertContains(response, destination)
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "TestPass123!",
            "next": destination,
        })
        self.assertRedirects(response, destination, fetch_redirect_response=False)

    def test_login_rejects_external_destination(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "TestPass123!",
            "next": "https://external.example/",
        })
        self.assertRedirects(response, reverse("attendance"), fetch_redirect_response=False)

    def make_child(self):
        group = Group.objects.create(name="Группа", trainer=Trainer.objects.create(full_name="Тренер"))
        return Child.objects.create(first_name="Имя", last_name="Фамилия", birth_year=2015, group=group)

    def test_reason_cannot_overwrite_visit(self):
        self.client.force_login(self.user)
        child = self.make_child()
        today = timezone.localdate()
        ScheduleSlot.objects.create(group=child.group, weekday=today.weekday(), start_time=time(18))
        mark = Attendance.objects.create(child=child, date=today, group_snapshot=child.group, status=Attendance.Status.PRESENT)
        response = self.client.post(reverse("attendance_reason"), {
            "child_id": child.pk, "group_id": child.group_id, "kind": "sick",
            "date_from": today.isoformat(), "date_to": today.isoformat(),
        })
        self.assertEqual(response.status_code, 409)
        mark.refresh_from_db()
        self.assertEqual(mark.status, Attendance.Status.PRESENT)
        self.assertFalse(AttendanceReason.objects.exists())

    def test_cancel_reason_keeps_history_and_visits(self):
        self.client.force_login(self.user)
        child = self.make_child()
        today = timezone.localdate()
        reason = AttendanceReason.objects.create(child=child, kind="sick", date_from=today, date_to=today + timedelta(days=1))
        visit = Attendance.objects.create(child=child, date=today, reason=reason, status="present")
        sick = Attendance.objects.create(child=child, date=today + timedelta(days=1), reason=reason, status="sick")
        response = self.client.post(reverse("cancel_reason", args=[reason.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AttendanceReason.objects.filter(pk=reason.pk).exists())
        self.assertTrue(Attendance.objects.filter(pk=visit.pk).exists())
        self.assertFalse(Attendance.objects.filter(pk=sick.pk).exists())

    def test_document_dates_can_change_without_reupload(self):
        data = {"valid_from": "2026-09-01", "valid_until": "2027-03-01", "note": "Уточнено"}
        self.assertTrue(ChildDocumentUploadForm(data, has_document=True).is_valid())
        self.assertFalse(ChildDocumentUploadForm(data, has_document=False).is_valid())

    def test_card_rejects_external_return_url(self):
        self.client.force_login(self.user)
        child = self.make_child()
        response = self.client.get(reverse("child_card", args=[child.pk]), {"next": "https://external.example/"})
        self.assertEqual(response.context["workflow_return_url"], "")

    def test_list_url_keeps_filters_but_removes_editor_state(self):
        request = RequestFactory().get("/?q=Иван&state=all&edit=7&new_payment=1&next=https://external.example/")
        result = list_url(request, "newcomers")
        from urllib.parse import urlsplit, parse_qs
        self.assertEqual(urlsplit(result).path, reverse("newcomers"))
        self.assertEqual(parse_qs(urlsplit(result).query), {"q": ["Иван"], "state": ["all"]})

    def test_trainer_save_and_cancel_keep_filters(self):
        self.client.force_login(self.user)
        trainer = Trainer.objects.create(full_name="Тренер", is_active=False)
        url = reverse("trainer_list") + f"?state=archive&edit={trainer.pk}"
        response = self.client.get(url)
        self.assertContains(response, 'href="' + reverse("trainer_list") + '?state=archive"')
        response = self.client.post(url, {"full_name": "Новое имя"})
        self.assertRedirects(response, reverse("trainer_list") + "?state=archive", fetch_redirect_response=False)

    def test_legacy_group_editor_keeps_filter(self):
        self.client.force_login(self.user)
        child = self.make_child()
        response = self.client.get(reverse("group_edit", args=[child.group_id]) + "?state=inactive&trainer=1")
        self.assertRedirects(response, reverse("group_list") + f"?state=inactive&trainer=1&edit={child.group_id}", fetch_redirect_response=False)

    def test_subscription_history_pages_do_not_lose_records(self):
        from .finance_ui import subscription_history_context
        child = self.make_child()
        today = timezone.localdate()
        Subscription.objects.bulk_create([
            Subscription(child=child, group=child.group, start_date=today, end_date=today + timedelta(days=30), price=100)
            for _ in range(65)
        ])
        seen = []
        for number, expected in [(1, 30), (2, 30), (3, 5)]:
            context = subscription_history_context(RequestFactory().get(f"/?sub_page={number}&sub_q=Фамилия&edit_subscription=1"))
            page = context["subscription_page"]
            self.assertEqual(len(page), expected)
            self.assertEqual(page.paginator.count, 65)
            seen.extend(item.pk for item in page)
            self.assertNotIn("edit_subscription", context["subscription_next_url"])
        self.assertEqual(len(set(seen)), 65)

    def test_subscription_history_filters_and_invalid_page(self):
        from .finance_ui import subscription_history_context
        child = self.make_child()
        today = timezone.localdate()
        sub = Subscription.objects.create(child=child, start_date=today, end_date=today, price=100, cancelled_at=timezone.now())
        context = subscription_history_context(RequestFactory().get("/?sub_q=Фамилия Имя&sub_state=cancelled&sub_page=wrong"))
        self.assertEqual(list(context["subscriptions"]), [sub])
        self.assertEqual(context["subscription_page"].number, 1)

    def test_tariff_error_keeps_full_page_and_only_binds_tariff(self):
        self.client.force_login(self.user)
        self.make_child()
        response = self.client.post(reverse("payments") + "?sub_q=Фамилия", {"action": "save_tariff", "tariff-name": "Черновик"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["tariff_form"].errors)
        self.assertFalse(response.context["subscription_form"].is_bound)
        self.assertContains(response, 'data-subscriptions-url="' + reverse("payment_subscriptions") + '"')
        self.assertContains(response, "Черновик")
        self.assertContains(response, "По этим фильтрам абонементов нет")

    def test_tariff_toggle_returns_to_history_filters(self):
        self.client.force_login(self.user)
        tariff = Tariff.objects.create(name="Тариф", price=100, sessions_total=8, duration_days=30)
        response = self.client.post(reverse("payments") + f"?sub_state=cancelled&sub_page=2&edit_tariff={tariff.pk}", {"action": "toggle_tariff", "tariff_id": tariff.pk})
        self.assertRedirects(response, reverse("payments") + "?sub_state=cancelled&sub_page=2", fetch_redirect_response=False)

    def test_payment_choices_require_login_and_valid_child(self):
        url = reverse("payment_subscriptions")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 400)
        self.assertEqual(self.client.get(url, {"child_id": "wrong"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"child_id": 999999}).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_payment_choices_are_scoped_complete_and_include_archived_child(self):
        self.client.force_login(self.user)
        child = self.make_child()
        child.status = Child.Status.ARCHIVED
        child.save(update_fields=["status"])
        other = self.make_child()
        today = timezone.localdate()
        Subscription.objects.bulk_create([
            Subscription(child=child, group=child.group, start_date=today, end_date=today, price=100)
            for _ in range(305)
        ])
        cancelled = Subscription.objects.create(child=child, start_date=today, end_date=today, price=100, cancelled_at=timezone.now())
        foreign = Subscription.objects.create(child=other, start_date=today, end_date=today, price=100)
        response = self.client.get(reverse("payment_subscriptions"), {"child_id": child.pk})
        ids = {item["id"] for item in response.json()["subscriptions"]}
        self.assertEqual(len(ids), 305)
        self.assertNotIn(cancelled.pk, ids)
        self.assertNotIn(foreign.pk, ids)
        self.assertIn("no-store", response["Cache-Control"])
        page = self.client.get(reverse("payments"))
        self.assertNotIn("payment_subscriptions", page.context)
        self.assertContains(page, 'data-payment-submit disabled')

    def test_payment_validation_preserves_draft_and_does_not_change_trial(self):
        self.client.force_login(self.user)
        child = self.make_child()
        child.status = Child.Status.TRIAL
        child.save(update_fields=["status"])
        today = timezone.localdate()
        sub = Subscription.objects.create(child=child, group=child.group, start_date=today, end_date=today, price=100)
        data = {"action": "payment", "submission_token": self.client.get(reverse("payments")).context["payment_token"], "child_id": child.pk, "subscription_id": sub.pk,
                "working_group_id": child.group_id, "amount": "-15", "date": today.isoformat()}
        response = self.client.post(reverse("payments") + "?sub_page=2", data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="payment-modal" class="modal open"')
        self.assertContains(response, 'value="-15"')
        self.assertContains(response, f'data-initial-subscription="{sub.pk}"')
        self.assertEqual(response.context["payment_form"]["working_group_id"].value(), str(child.group_id))
        self.assertFalse(child.payments.exists())
        child.refresh_from_db()
        self.assertEqual(child.status, Child.Status.TRIAL)
        data["amount"] = "0.50"
        response = self.client.post(reverse("payments") + "?sub_page=2", data)
        self.assertRedirects(response, reverse("payments") + "?sub_page=2", fetch_redirect_response=False)
        self.assertEqual(child.payments.count(), 1)

    def test_payment_rejects_missing_child_and_foreign_subscription_in_form(self):
        self.client.force_login(self.user)
        child = self.make_child()
        other = self.make_child()
        today = timezone.localdate()
        sub = Subscription.objects.create(child=other, start_date=today, end_date=today, price=100)
        for child_id, field in [("wrong", "child_id"), (child.pk, "subscription_id")]:
            response = self.client.post(reverse("payments"), {"action": "payment", "submission_token": self.client.get(reverse("payments")).context["payment_token"], "child_id": child_id,
                "subscription_id": sub.pk, "amount": "1500", "date": today.isoformat()})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["payment_form"].errors.get(field))
            self.assertContains(response, 'value="1500"')
        self.assertFalse(child.payments.exists())
        self.assertFalse(other.payments.exists())

    def test_attendance_without_schedule_shows_roster_and_setup(self):
        self.client.force_login(self.user)
        child = self.make_child()
        response = self.client.get(reverse("attendance"), {"group_id": child.group_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["child"] for row in response.context["children_data"]], [child])
        self.assertContains(response, "data-attendance-roster")
        self.assertContains(response, reverse("child_card", args=[child.pk]))
        self.assertContains(response, reverse("group_list") + f"?edit={child.group_id}")
        self.assertNotContains(response, 'class="data-table attendance-grid"')
        self.assertNotContains(response, 'id="move-class-modal"')

    def test_attendance_roster_respects_archive_filter(self):
        self.client.force_login(self.user)
        child = self.make_child()
        child.status = Child.Status.ARCHIVED
        child.save(update_fields=["status"])
        active = self.client.get(reverse("attendance"), {"group_id": child.group_id})
        self.assertEqual(active.context["children_data"], [])
        archived = self.client.get(reverse("attendance"), {"group_id": child.group_id, "show_archived": "1"})
        self.assertEqual([row["child"] for row in archived.context["children_data"]], [child])
        self.assertContains(archived, "Архив группы")

    def test_attendance_empty_day_keeps_roster_without_missing_schedule_warning(self):
        self.client.force_login(self.user)
        child = self.make_child()
        today = timezone.localdate()
        ScheduleSlot.objects.create(group=child.group, weekday=(today.weekday() + 1) % 7, start_time=time(18))
        response = self.client.get(reverse("attendance"), {"group_id": child.group_id, "period": "day", "ref_date": today.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-attendance-roster")
        self.assertContains(response, "В этом периоде нет занятий")
        self.assertNotContains(response, "Нет расписания")

    def test_attendance_empty_generated_window_does_not_index_missing_date(self):
        from unittest.mock import patch
        self.client.force_login(self.user)
        child = self.make_child()
        ScheduleSlot.objects.create(group=child.group, weekday=0, start_time=time(18))
        with patch("crm.views.generate_class_dates", return_value=[]):
            response = self.client.get(reverse("attendance"), {"group_id": child.group_id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-attendance-roster")
        self.assertEqual(len(response.context["children_data"]), 1)

    def make_editable_reason(self):
        child = self.make_child()
        today = timezone.localdate()
        for offset in range(3):
            ScheduleSlot.objects.create(group=child.group, weekday=(today + timedelta(days=offset)).weekday(), start_time=time(18))
        reason = AttendanceReason.objects.create(child=child, kind="sick", date_from=today,
            date_to=today + timedelta(days=1), comment="Исходный", document="attendance_reasons/kept.pdf")
        for offset in range(2):
            Attendance.objects.create(child=child, group_snapshot=child.group, date=today + timedelta(days=offset), status="sick", reason=reason)
        return child, reason, today

    def test_edit_reason_shifts_marks_and_keeps_document(self):
        self.client.force_login(self.user)
        child, reason, today = self.make_editable_reason()
        response = self.client.post(reverse("edit_reason", args=[reason.pk]), {
            "date_from": (today + timedelta(days=1)).isoformat(), "date_to": (today + timedelta(days=2)).isoformat(), "comment": "Уточнено",
        })
        self.assertRedirects(response, reverse("child_card", args=[child.pk]) + "#absence-reasons", fetch_redirect_response=False)
        reason.refresh_from_db()
        self.assertEqual(reason.document.name, "attendance_reasons/kept.pdf")
        self.assertEqual(reason.comment, "Уточнено")
        self.assertEqual(set(reason.attendances.values_list("date", flat=True)), {today + timedelta(days=1), today + timedelta(days=2)})
        self.assertEqual(set(reason.attendances.values_list("comment", flat=True)), {"Уточнено"})

    def test_edit_reason_conflict_preserves_old_period_and_all_marks(self):
        self.client.force_login(self.user)
        child, reason, today = self.make_editable_reason()
        visit = Attendance.objects.create(child=child, group_snapshot=child.group, date=today + timedelta(days=2), status="present", charge_amount=100)
        response = self.client.post(reverse("edit_reason", args=[reason.pk]), {
            "date_from": today.isoformat(), "date_to": visit.date.isoformat(), "comment": "Черновик",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertContains(response, "Черновик")
        reason.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(reason.date_to, today + timedelta(days=1))
        self.assertEqual(reason.comment, "Исходный")
        self.assertEqual(reason.attendances.count(), 2)
        self.assertEqual(visit.charge_amount, 100)

    def test_edit_cancelled_reason_does_not_recreate_marks(self):
        self.client.force_login(self.user)
        child, reason, today = self.make_editable_reason()
        reason.attendances.all().delete()
        response = self.client.post(reverse("edit_reason", args=[reason.pk]), {"date_from": today.isoformat(), "date_to": today.isoformat(), "comment": "Не применять"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(reason.attendances.exists())

    def test_edit_reason_invalid_period_has_no_side_effects(self):
        self.client.force_login(self.user)
        child, reason, today = self.make_editable_reason()
        response = self.client.post(reverse("edit_reason", args=[reason.pk]), {"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat(), "comment": "Ошибка"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("date_to"))
        self.assertEqual(reason.attendances.count(), 2)

    def test_child_card_post_forms_opt_into_draft_guard(self):
        from html.parser import HTMLParser
        class FormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms = []
            def handle_starttag(self, tag, attrs):
                if tag == "form":
                    attributes = dict(attrs)
                    if attributes.get("method", "").lower() == "post":
                        self.forms.append(attributes)
        self.client.force_login(self.user)
        child = self.make_child()
        response = self.client.get(reverse("child_card", args=[child.pk]))
        parser = FormParser()
        parser.feed(response.content.decode())
        self.assertGreater(len(parser.forms), 3)
        self.assertTrue(all("data-guard-draft" in form for form in parser.forms))

    def test_competition_create_modes_do_not_reuse_edit_instances(self):
        from .models import Competition, CompetitionEntry, Apparatus
        self.client.force_login(self.user)
        child = self.make_child()
        competition = Competition.objects.create(name="Старое соревнование", date=timezone.localdate())
        apparatus = Apparatus.objects.create(competition=competition, name="Бревно")
        entry = CompetitionEntry.objects.create(competition=competition, child=child)
        cases = [
            ("new_competition", "edit_competition", competition.pk, "competition_form"),
            ("new_apparatus", "edit_apparatus", apparatus.pk, "apparatus_form"),
            ("new_entry", "edit_entry", entry.pk, "entry_form"),
        ]
        for new, edit, pk, form in cases:
            with self.subTest(mode=new):
                response = self.client.get(reverse("competitions"), {"competition": competition.pk, new: "1", edit: pk})
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context[form].instance.pk)
                self.assertEqual(response.context["selected"].pk, competition.pk)
                self.assertNotIn(edit, response.context["workflow_list_url"])
        competition.refresh_from_db()
        self.assertEqual(competition.name, "Старое соревнование")

    def test_calendar_cancel_retains_day_and_scope_without_create_flag(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("calendar"), {
            "start": "2026-11-01", "day": "2026-11-15", "scope": "mine", "state": "open", "create": "1",
        })
        target = response.context["workflow_list_url"]
        self.assertIn("start=2026-11-01", target)
        self.assertIn("day=2026-11-15", target)
        self.assertIn("scope=mine", target)
        self.assertNotIn("create", target)
        self.assertContains(response, 'aria-label="Закрыть"')

    def salary_editor_setup(self):
        from datetime import date
        from .models import SalaryAdjustment
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        trainer = Trainer.objects.create(full_name="Архивный тренер", is_active=False)
        return SalaryAdjustment.objects.create(trainer=trainer, month=date(2026, 8, 1), title="Доплата", amount=100)

    def test_salary_edit_preserves_row_month_and_archived_trainer(self):
        from .models import SalaryAdjustment, AuditEvent
        item = self.salary_editor_setup()
        url = reverse("salaries") + f"?month=2026-08&edit={item.pk}"
        response = self.client.post(url, {"action": "add_adjustment", "adjustment-trainer": item.trainer_id,
            "adjustment-title": "Уточнённое удержание", "adjustment-amount": "-50.25"})
        self.assertRedirects(response, reverse("salaries") + "?month=2026-08", fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertEqual(str(item.amount), "-50.25")
        self.assertEqual(item.title, "Уточнённое удержание")
        self.assertEqual(SalaryAdjustment.objects.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="salary.adjustment.edit").exists())

    def test_salary_edit_error_keeps_draft_and_original_amount(self):
        item = self.salary_editor_setup()
        response = self.client.post(reverse("salaries") + f"?month=2026-08&edit={item.pk}", {
            "action": "add_adjustment", "adjustment-trainer": item.trainer_id,
            "adjustment-title": "Черновик", "adjustment-amount": "не сумма"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Черновик")
        self.assertTrue(response.context["adjustment_form"].errors)
        item.refresh_from_db()
        self.assertEqual(item.amount, 100)
        self.assertEqual(item.title, "Доплата")

    def test_salary_editor_rejects_other_month_and_manager(self):
        item = self.salary_editor_setup()
        response = self.client.get(reverse("salaries") + f"?month=2026-09&edit={item.pk}")
        self.assertEqual(response.status_code, 404)
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        self.assertEqual(self.client.get(reverse("salaries") + f"?month=2026-08&edit={item.pk}").status_code, 403)

    def test_payment_replay_is_noop_and_changed_payload_is_rejected(self):
        self.client.force_login(self.user)
        child = self.make_child()
        token = self.client.get(reverse("payments")).context["payment_token"]
        data = {"action": "payment", "submission_token": token, "child_id": child.pk,
                "amount": "100", "date": timezone.localdate().isoformat()}
        for _ in range(2):
            response = self.client.post(reverse("payments"), data)
            self.assertEqual(response.status_code, 302)
        self.assertEqual(child.payments.count(), 1)
        data["amount"] = "200"
        response = self.client.post(reverse("payments"), data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["payment_form"].non_field_errors())
        self.assertEqual(child.payments.count(), 1)
        self.assertEqual(child.payments.get().amount, 100)

    def test_payment_requires_valid_actor_bound_token(self):
        from .payment_submission import issue_token
        self.client.force_login(self.user)
        child = self.make_child()
        for token in ["", "forged", issue_token(self.user.pk + 100)]:
            response = self.client.post(reverse("payments"), {"action": "payment", "submission_token": token,
                "child_id": child.pk, "amount": "100", "date": timezone.localdate().isoformat()})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["payment_form"].non_field_errors())
        self.assertFalse(child.payments.exists())

    def test_separate_payment_tokens_allow_legitimate_equal_payments(self):
        from .payment_submission import issue_token
        self.client.force_login(self.user)
        child = self.make_child()
        for _ in range(2):
            self.client.post(reverse("payments"), {"action": "payment", "submission_token": issue_token(self.user.pk),
                "child_id": child.pk, "amount": "100", "date": timezone.localdate().isoformat()})
        self.assertEqual(child.payments.count(), 2)

    def test_payment_admin_keeps_original_author_and_disallows_delete(self):
        from django.contrib.admin.sites import AdminSite
        from .admin import PaymentAdmin
        from .models import Payment
        child = self.make_child()
        other = get_user_model().objects.create_user(username="payment-editor")
        payment = Payment.objects.create(child=child, amount=100, created_by=self.user)
        request = RequestFactory().post("/admin/")
        request.user = other
        admin = PaymentAdmin(Payment, AdminSite())
        admin.save_model(request, payment, None, change=True)
        payment.refresh_from_db()
        self.assertEqual(payment.created_by_id, self.user.pk)
        self.assertFalse(admin.has_delete_permission(request, payment))

    def test_deleting_child_cannot_cascade_into_payment_history(self):
        from django.db.models.deletion import ProtectedError
        from .models import Payment
        child = self.make_child()
        payment = Payment.objects.create(child=child, amount=100)
        with self.assertRaises(ProtectedError):
            child.delete()
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
