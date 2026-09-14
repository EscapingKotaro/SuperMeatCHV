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

    def test_clients_dropdown_orders_newcomers_before_applications(self):
        response = self.client.get(reverse("clients"))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        start = html.index('id="dropdown-clients"')
        end = html.index('id="dropdown-team"', start)
        menu = html[start:end]

        self.assertLess(
            menu.index(reverse("clients")),
            menu.index(reverse("newcomers")),
        )
        self.assertLess(
            menu.index(reverse("newcomers")),
            menu.index(reverse("applications")),
        )

    def test_child_card_does_not_duplicate_discount_percentages(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import Subscription

        today = timezone.localdate()
        self.child.discount_percent = 5
        self.child.save(update_fields=["discount_percent"])

        Subscription.objects.create(
            child=self.child,
            group=self.group,
            start_date=today,
            end_date=today + timedelta(days=30),
            sessions_total=8,
            price=4500,
            discount_percent=5,
            promo="Осень",
            promo_percent=10,
            promo_start_date=today,
            promo_end_date=today + timedelta(days=15),
            is_active=True,
        )

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        self.assertNotIn('data-child-indicator="discount"', html)
        self.assertNotIn("Индивидуальная скидка 5%", html)
        self.assertNotIn("5%", html)
        self.assertEqual(html.count("Осень · 10%"), 1)

    def test_child_card_hides_legacy_membership_implementation_details(self):
        self.child.group_memberships.all().delete()

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertContains(response, self.group.trainer.full_name)
        self.assertContains(response, "Основная группа")
        self.assertNotContains(response, "Только чтение")
        self.assertNotContains(response, "связь membership отсутствует")
        self.assertNotContains(response, "Восстановить связь")
        self.assertFalse(self.child.group_memberships.exists())

    def test_group_picker_is_trainer_first_and_subscription_mode_is_explicit(self):
        primary_extra = Group.objects.create(
            name="Архивная группа",
            trainer=self.group.trainer,
        )
        trainer_two = Trainer.objects.create(full_name="Анна Миронова")
        group_two = Group.objects.create(
            name="Младшая группа",
            trainer=trainer_two,
        )
        trainer_three = Trainer.objects.create(full_name="Ирина Белова")
        group_three = Group.objects.create(
            name="Средняя группа · Котельники",
            trainer=trainer_three,
        )

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        picker_start = html.index('data-membership-group-picker')
        picker_end = html.index('Требовать абонемент для этой группы')
        picker = html[picker_start:picker_end]

        for trainer_name, group_name in (
            (self.group.trainer.full_name, primary_extra.name),
            (trainer_two.full_name, group_two.name),
            (trainer_three.full_name, group_three.name),
        ):
            self.assertIn(trainer_name, picker)
            self.assertIn(group_name, picker)
            self.assertLess(
                picker.index(trainer_name),
                picker.index(group_name),
            )

        self.assertNotIn("раскрыть", picker)
        self.assertContains(
            response,
            "Требовать абонемент для этой группы",
        )
        self.assertContains(
            response,
            "без списания абонемента и без оформления долга",
        )
        self.assertNotContains(
            response,
            "Показывать состояние абонемента",
        )
        self.assertContains(response, "Занятия: по абонементу")

    def test_child_visit_statistics_use_non_overflowing_grid(self):
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        start = html.index("data-period-statistics")
        end = html.index("Отметки выбранного периода", start)
        statistics = html[start:end]

        self.assertIn("grid-cols-2", statistics)
        self.assertIn("sm:grid-cols-3", statistics)
        self.assertNotIn("sm:grid-cols-6", statistics)
        self.assertEqual(statistics.count('data-period-stat="'), 6)
        self.assertEqual(statistics.count("break-words"), 6)
        self.assertIn("Заморозка", statistics)
        self.assertIn("Больничный", statistics)

    def test_subscription_boundary_is_thick_and_contrasting(self):
        styles = render_to_string(
            "crm/includes/attendance_styles.html",
        )

        self.assertIn(
            "border-right:3px solid #475569",
            styles,
        )
        self.assertIn(
            "border-left:3px solid #475569",
            styles,
        )
        self.assertNotIn(
            "border-right:2px solid #f87171",
            styles,
        )
        self.assertNotIn(
            "border-left:2px solid #f87171",
            styles,
        )

    def test_contacts_and_document_copy_are_universal_and_russian(self):
        from .forms import ChildForm

        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(response.status_code, 200)
        html = " ".join(response.content.decode().split())

        self.assertIn("Основной контакт", html)
        self.assertIn("Дополнительный контакт", html)
        self.assertNotIn("Родитель 1", html)
        self.assertNotIn("Родитель 2", html)
        self.assertNotIn("аллерт", html.lower())
        self.assertIn(
            f"Проблем с документами: {len(response.context['document_alerts'])}",
            html,
        )

        form = ChildForm(instance=self.child)
        self.assertEqual(
            form.fields["parent_name"].label,
            "Основной контакт",
        )
        self.assertEqual(
            form.fields["parent_phone"].label,
            "Телефон основного контакта",
        )
        self.assertEqual(
            form.fields["second_parent_name"].label,
            "Дополнительный контакт",
        )
        self.assertEqual(
            form.fields["second_parent_phone"].label,
            "Телефон дополнительного контакта",
        )

        clients = self.client.get(reverse("clients"))
        self.assertEqual(clients.status_code, 200)
        clients_html = clients.content.decode().lower()
        self.assertNotIn("алерт", clients_html)
        self.assertContains(clients, "Есть проблемы")
        self.assertContains(clients, "Без проблем")
        self.assertContains(clients, "В порядке")

    def test_custom_attendance_period_stays_inside_card(self):
        response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
            {"attendance_period": "custom"},
        )
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        start = html.index("data-custom-attendance-period")
        end = html.index("Показать", start)
        period = html[start:end]

        self.assertNotIn("sm:grid-cols-[1fr_1fr_auto]", period)
        self.assertEqual(period.count("min-w-0"), 5)
        self.assertEqual(period.count("max-w-full"), 2)
        self.assertIn('name="attendance_from"', period)
        self.assertIn('name="attendance_to"', period)

    def test_management_profile_and_users_copy_is_user_facing(self):
        from types import SimpleNamespace

        from django.utils import timezone

        request = RequestFactory().get("/")
        request.user = self.user
        event = SimpleNamespace(
            actor=self.user,
            description="Проверочное действие",
            created_at=timezone.now(),
            action="child_deleted",
        )
        boss = render_to_string(
            "crm/boss.html",
            {
                "events": [event],
                "events_count": 1,
                "trainer_rows": [],
                "top_trainers_attendance": [],
                "top_groups_attendance": [],
                "top_trial_groups": [],
                "top_competition_groups": [],
            },
            request=request,
        )
        self.assertIn("Показатели тренеров", boss)
        self.assertIn("Скачать таблицу", boss)
        self.assertIn("Записей в журнале: 1", boss)
        self.assertNotIn("KPI", boss)
        self.assertNotIn("child_deleted", boss)
        self.assertNotIn(">Excel<", boss)

        profile = render_to_string(
            "crm/profile.html",
            {
                "profile_form": [],
                "password_form": [],
                "attendance_visual": {
                    "show_subscription_boundary": True,
                    "highlight_today": True,
                    "show_legend": True,
                },
            },
            request=request,
        )
        self.assertIn("Учётная запись активна", profile)
        self.assertIn("Контрастная вертикальная линия", profile)
        self.assertNotIn("Аккаунт активен", profile)
        self.assertNotIn("Красная вертикальная линия", profile)

        other = get_user_model().objects.create_user(
            username="ui-copy-other",
        )
        users = render_to_string(
            "crm/users.html",
            {
                "users": [self.user, other],
                "current_role": "admin",
                "form": [],
            },
            request=request,
        )
        self.assertIn("Эл. почта не указана", users)
        self.assertIn('placeholder="Эл. почта"', users)
        self.assertIn("Текущая учётная запись", users)
        self.assertIn("Создать пользователя", users)
        self.assertNotIn("Email", users)
        self.assertNotIn("аккаунт", users.lower())

    def test_finance_pages_use_clear_russian_copy(self):
        request = RequestFactory().get("/")
        request.user = self.user

        statistics = render_to_string(
            "crm/statistics.html",
            {
                "is_senior": True,
                "month_start": date(2026, 9, 1),
                "revenue_month": 0,
                "potential": 0,
                "bar_scale": 1,
                "target": None,
                "groups_stats": [],
                "trainers_stats": [],
            },
            request=request,
        )
        self.assertIn("Зарплаты тренеров", statistics)
        self.assertIn("Расчёт и выгрузка", statistics)
        self.assertNotIn("ЗП тренеров", statistics)
        self.assertNotIn("Excel", statistics)

        salaries = render_to_string(
            "crm/salaries.html",
            {
                "month_start": date(2026, 9, 1),
                "month_end": date(2026, 9, 30),
                "can_manage_salary": True,
                "editing_adjustment": None,
                "adjustment_form": [],
                "summary_rows": [],
                "trainers": [],
                "grand_total": 0,
            },
            request=request,
        )
        self.assertIn("Скачать таблицу", salaries)
        self.assertIn("Ручное начисление", salaries)
        self.assertIn("Персональные занятия", salaries)
        self.assertIn("Посещений", salaries)
        self.assertIn("Удалить ручное начисление?", salaries)
        self.assertNotIn("Excel", salaries)
        self.assertNotIn("строку ЗП", salaries)
        self.assertNotIn("Персоналки", salaries)

    def test_newcomer_trainer_and_group_filters_are_selectable(self):
        second_trainer = Trainer.objects.create(
            full_name="Анна Миронова",
        )
        second_group = Group.objects.create(
            name="Младшая группа",
            trainer=second_trainer,
        )
        Newcomer.objects.create(
            full_name="Пробник первый",
            trainer=self.group.trainer,
            group=self.group,
        )
        Newcomer.objects.create(
            full_name="Пробник второй",
            trainer=second_trainer,
            group=second_group,
        )

        response = self.client.get(reverse("newcomers"))
        self.assertEqual(response.status_code, 200)

        html = " ".join(response.content.decode().split())
        start = html.index("data-newcomer-filters")
        end = html.index("data-clear-filters", start)
        filters = html[start:end]

        self.assertIn(
            '<select class="field" data-filter="trainer"',
            filters,
        )
        self.assertIn(
            '<select class="field" data-filter="group"',
            filters,
        )
        self.assertIn("Тренер: все", filters)
        self.assertIn("Группа: все", filters)
        self.assertNotIn(
            'type="search" class="field" placeholder="Тренер"',
            filters,
        )
        self.assertNotIn(
            'type="search" class="field" placeholder="Группа"',
            filters,
        )

        self.assertContains(
            response,
            "populateFilterSelect(controls.trainer, 'trainer', 'Тренер: все')",
        )
        self.assertContains(
            response,
            "populateFilterSelect(controls.group, 'group', 'Группа: все')",
        )
        self.assertContains(
            response,
            "lower(row.dataset.trainer) === lower(v.trainer)",
        )
        self.assertContains(
            response,
            "lower(row.dataset.group) === lower(v.group)",
        )

    def test_task_form_has_two_clear_dates_without_microcopy(self):
        from .forms import ManagerTaskForm

        form = ManagerTaskForm()

        self.assertNotIn("scheduled_end_at", form.fields)
        self.assertEqual(
            form.fields["scheduled_at"].label,
            "Дата и время задачи",
        )
        self.assertEqual(
            form.fields["due_date"].label,
            "Выполнить до",
        )
        self.assertEqual(form.fields["assignee"].help_text, "")

        invalid = ManagerTaskForm(
            data={
                "title": "Проверить документы",
                "scheduled_at": "2026-09-15T10:00",
                "due_date": "2026-09-14",
            },
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn(
            "Срок выполнения не может быть раньше даты задачи",
            invalid.errors["due_date"],
        )

        response = self.client.get(reverse("calendar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Дата и время задачи")
        self.assertContains(response, "Выполнить до")
        self.assertNotContains(response, "Окончание в календаре")
        self.assertNotContains(
            response,
            "Задача появится в календаре и уведомлениях",
        )
        self.assertNotContains(
            response,
            "Пусто — общая задача для всей администрации",
        )

    def test_modal_scroll_contract_covers_all_modal_shapes(self):
        from pathlib import Path

        from django.contrib.staticfiles import finders

        group_response = self.client.get(
            reverse("group_list"),
            {"edit": self.group.pk},
        )
        self.assertEqual(group_response.status_code, 200)
        self.assertContains(group_response, 'id="group-modal"')
        self.assertContains(group_response, 'class="modal open"')
        self.assertContains(group_response, 'class="modal-body"')
        self.assertContains(group_response, "crm/app.css?v=5")

        child_response = self.client.get(
            reverse("child_card", args=[self.child.pk]),
        )
        self.assertEqual(child_response.status_code, 200)
        child_html = " ".join(child_response.content.decode().split())
        child_modal_start = child_html.index('id="child-edit-modal"')
        child_modal_end = child_html.index("</section>", child_modal_start)
        child_modal = child_html[child_modal_start:child_modal_end]
        self.assertIn("<form ", child_modal)
        self.assertIn('class="modal-body', child_modal)

        attendance_response = self.client.get(
            reverse("attendance"),
            {"group_id": self.group.pk},
        )
        self.assertEqual(attendance_response.status_code, 200)
        self.assertContains(
            attendance_response,
            'id="attendance-reason-modal" class="hidden fixed inset-0',
        )

        css_path = finders.find("crm/app.css")
        self.assertIsNotNone(css_path)
        css = Path(css_path).read_text(encoding="utf-8")

        self.assertIn(
            ".modal.open{display:flex;min-height:0;flex-direction:column;"
            "overflow-y:auto;",
            css,
        )
        self.assertIn(
            ".modal>form{display:flex;max-height:inherit;",
            css,
        )
        self.assertIn(
            ".modal>.modal-body{flex:0 0 auto;overflow:visible}",
            css,
        )
        self.assertIn(
            ".modal>form>.modal-body{flex:1 1 auto;overflow-y:auto;",
            css,
        )
        self.assertIn(
            ".crm-overlay-panel{max-height:calc(100dvh - 2rem);"
            "overflow-y:auto;",
            css,
        )

    def test_attendance_empty_group_keeps_table_and_shows_empty_state(self):
        from datetime import time

        from django.utils import timezone

        from .models import ScheduleSlot

        empty_group = Group.objects.create(
            name="Пустая группа",
            trainer=self.group.trainer,
        )
        today = timezone.localdate()
        ScheduleSlot.objects.create(
            group=empty_group,
            weekday=today.weekday(),
            start_time=time(18, 0),
        )

        response = self.client.get(
            reverse("attendance"),
            {
                "group_id": empty_group.pk,
                "ref_date": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["children_data"])
        self.assertTrue(response.context["week_data"])

        html = " ".join(response.content.decode().split())
        expected_colspan = len(response.context["week_data"]) + 1

        self.assertIn("data-attendance-empty-state", html)
        self.assertIn(f'colspan="{expected_colspan}"', html)
        self.assertIn("В группе пока нет спортсменов", html)
        self.assertIn(
            "Добавьте спортсмена, чтобы начать вести посещения.",
            html,
        )
        self.assertIn('data-modal="child-create-modal"', html)
        self.assertNotIn('colspan="100"', html)
