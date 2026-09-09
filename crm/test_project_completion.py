from datetime import date, time, timedelta
from decimal import Decimal
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .forms import LeadForm, SubscriptionForm
from .intake_parser import parse_application
from .models import (
    Attendance, Camp, CampStay, Child, Competition, CompetitionDocument, CompetitionEntry,
    Group, Lead, Newcomer, Notification, Payment, Role, ScheduleSlot, StaffProfile,
    Subscription, Tariff, Trainer, age_label, expire_trials,
)
from .context_processors import sync_subscription_notifications, sync_today_trials
from .views import build_group_stats, build_renewal_rows


class ProjectCompletionTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.user = get_user_model().objects.create_user('release-check', password='test-password', is_staff=True)
        StaffProfile.objects.create(user=self.user, role=Role.BOSS)
        self.trainer = Trainer.objects.create(full_name='Тренер проверки')
        self.group = Group.objects.create(name='Группа проверки', trainer=self.trainer)
        for weekday in (0, 2):
            ScheduleSlot.objects.create(group=self.group, weekday=weekday, start_time=time(18))
        self.child = Child.objects.create(last_name='Тестовая', first_name='Анна', birth_year=2016, group=self.group)
        self.client.force_login(self.user)

    def subscription(self, **extra):
        values = dict(child=self.child, start_date=self.today-timedelta(days=10), end_date=self.today+timedelta(days=15), sessions_total=8, price=Decimal('5000'))
        values.update(extra)
        return Subscription.objects.create(**values)

    def trial(self, age=14):
        self.child.status = Child.Status.TRIAL
        self.child.trial_from = self.today-timedelta(days=age)
        self.child.save()

    def test_trial_before_boundary_is_retained(self):
        self.trial(13)
        self.assertEqual(expire_trials(self.today), 0)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.TRIAL)

    def test_trial_boundary_preserves_history_and_kpi(self):
        self.trial()
        Attendance.objects.create(child=self.child, date=self.today-timedelta(days=1), status='present')
        self.assertEqual(expire_trials(self.today), 1)
        self.assertEqual(expire_trials(self.today), 0)
        self.child.refresh_from_db()
        self.assertEqual(self.child.group_id, self.group.pk)
        self.assertEqual(self.child.departure_trainer_id, self.trainer.pk)
        self.assertEqual(self.child.archived_at, self.today)
        self.assertEqual(self.child.attendances.get().trainer_snapshot_id, self.trainer.pk)
        page = self.client.get(reverse('boss'))
        self.assertEqual(page.context['trainer_rows'][0]['lost'], 1)

    def test_trial_with_historical_real_payment_not_lost(self):
        Payment.objects.create(child=self.child, amount=1)
        self.trial()
        self.assertEqual(expire_trials(self.today), 0)

    def test_expiration_command_does_not_depend_on_attendance(self):
        self.trial()
        call_command('expire_trials', stdout=StringIO())
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.LOST)

    def test_any_authenticated_page_sweeps_all_groups(self):
        self.trial()
        self.client.get(reverse('profile'))
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.LOST)

    def test_subscription_without_payment_keeps_trial(self):
        self.trial(2)
        tariff = Tariff.objects.create(name='Стандарт', sessions_total=8, duration_days=30, price=5000)
        self.client.post(reverse('payments'), {'action':'save_subscription', 'subscription-child':self.child.pk, 'subscription-tariff':tariff.pk, 'subscription-start_date':self.today.isoformat(), 'subscription-is_active':'on'})
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.TRIAL)
        self.assertEqual(self.child.subscriptions.count(), 1)

    def test_window_has_four_previous_and_three_future_on_monday(self):
        anchor = date(2026, 9, 7)
        response = self.client.get(reverse('attendance'), {'group_id':self.group.pk, 'ref_date':anchor.isoformat()})
        dates = [item['date'] for item in response.context['week_data']]
        self.assertEqual(dates, [date(2026,8,24), date(2026,8,26), date(2026,8,31), date(2026,9,2), anchor, date(2026,9,9), date(2026,9,14), date(2026,9,16)])
        self.assertEqual(response.context['prev_ref'], '2026-09-02')
        self.assertEqual(response.context['next_ref'], '2026-09-09')

    def test_duplicate_daily_slots_do_not_duplicate_columns(self):
        ScheduleSlot.objects.create(group=self.group, weekday=0, start_time=time(19))
        response = self.client.get(reverse('attendance'), {'group_id':self.group.pk, 'ref_date':'2026-09-08'})
        dates = [row['date'] for row in response.context['week_data']]
        self.assertEqual(len(set(dates)), 8)
        self.assertEqual(dates[4], date(2026,9,9))

    def test_cancel_subscription_removes_charge_but_keeps_history(self):
        old = self.subscription(is_active=False, price=1000)
        current = self.subscription()
        payment = Payment.objects.create(child=self.child, amount=500)
        mark = Attendance.objects.create(child=self.child, date=self.today, status='present')
        data = {'subscription_id':current.pk, 'child_id':self.child.pk, 'confirmed':'1'}
        response = self.client.post(reverse('cancel_subscription'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.child.debt(), Decimal('500'))
        self.assertEqual(self.child.sessions_left(), 0)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertTrue(Attendance.objects.filter(pk=mark.pk).exists())
        self.assertTrue(Subscription.objects.filter(pk=old.pk).exists())
        current.refresh_from_db()
        cancelled_at = current.cancelled_at
        self.client.post(reverse('cancel_subscription'), data)
        current.refresh_from_db()
        self.assertEqual(current.cancelled_at, cancelled_at)
        self.assertEqual(build_renewal_rows(self.today.replace(day=1), self.today+timedelta(days=31)), [])

    def test_cancel_requires_confirmation_and_matching_child(self):
        current = self.subscription()
        self.assertEqual(self.client.post(reverse('cancel_subscription'), {'subscription_id':current.pk,'child_id':self.child.pk}).status_code, 400)
        self.assertEqual(self.client.post(reverse('cancel_subscription'), {'subscription_id':current.pk,'child_id':99999,'confirmed':'1'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('cancel_subscription')).status_code, 405)

    def test_age_declensions(self):
        for text, expected in [('12','12 лет'), ('4,10','4 года 10 месяцев'), ('1,2','1 год 2 месяца'), ('8 месяцев','8 месяцев'), ('21','21 год'), ('11','11 лет')]:
            with self.subTest(text=text):
                self.assertEqual(age_label(age_text=text), expected)
        self.assertEqual(age_label(date(2025,7,10), today=date(2026,9,9)), '1 год 1 месяц')

    def test_lead_conversion_is_idempotent(self):
        lead = Lead.objects.create(full_name='Пробная Анна', group=self.group)
        for _ in range(2):
            self.client.post(reverse('applications'), {'action':'create_newcomer', 'lead_id':lead.pk})
        self.assertEqual(lead.newcomers.count(), 1)

    def test_shared_intake_fields_sync_both_directions(self):
        lead = Lead.objects.create(full_name='Анна', phone='123')
        newcomer = Newcomer.objects.create(lead=lead, full_name='Анна', phone='123')
        lead.phone='456'; lead.save(update_fields=['phone'])
        newcomer.refresh_from_db(); self.assertEqual(newcomer.phone,'456')
        newcomer.full_name='Анна Петрова'; newcomer.save(update_fields=['full_name'])
        lead.refresh_from_db(); self.assertEqual(lead.full_name,'Анна Петрова')

    def test_lead_projects_operational_state_and_real_payment(self):
        lead = Lead.objects.create(full_name='Анна', group=self.group, trial_at=timezone.now()-timedelta(days=3))
        newcomer = Newcomer.objects.create(lead=lead, full_name='Анна', group=self.group, trainer=self.trainer, trial_at=timezone.now(), attended=True, child=self.child, comment='Перенос по просьбе родителя')
        Payment.objects.create(child=self.child, amount=100)
        response = self.client.get(reverse('applications'))
        self.assertContains(response, 'Пришёл')
        self.assertContains(response, 'Оплачено')
        self.assertContains(response, newcomer.comment)
        form = LeadForm(instance=lead)
        self.assertTrue(form.fields['trial_at'].disabled)

    def test_paid_is_not_an_editable_claim(self):
        newcomer = Newcomer.objects.create(full_name='Анна', child=self.child, paid=True)
        self.assertFalse(newcomer.has_paid)
        payment = Payment.objects.create(child=self.child, amount=100)
        self.assertTrue(newcomer.has_paid)
        payment.delete()
        self.assertFalse(newcomer.has_paid)

    def test_parser_website_and_vk_samples(self):
        website = 'Имя: Анна Петрова\nТелефон: 8 (999) 123-45-67\nВозраст: 7 лет\nИсточник: Сайт\nКампания: Сентябрь\nВремя звонка: после 18:00'
        parsed = parse_application(website)
        self.assertEqual(parsed['full_name'], 'Анна Петрова')
        self.assertEqual(parsed['phone'], '+79991234567')
        self.assertEqual(parsed['source'], 'Сайт')
        self.assertIn('после 18:00', parsed['comment'])
        vk = 'Вопрос: Имя и возраст ребёнка?\nОтвет: Анна, 10 лет\nВопрос: Телефон родителя\nОтвет: +7 999 123 45 67\nГруппа объявлений: Люберцы\nОбъявление: Набор'
        parsed = parse_application(vk)
        self.assertEqual(parsed['full_name'], 'Анна')
        self.assertEqual(parsed['age_text'], '10')
        self.assertIn('Люберцы', parsed['comment'])
        age_only = parse_application('Вопрос: Имя и возраст ребёнка?\nОтвет: Возраст 10 лет')
        self.assertEqual(age_only['age_text'], '10')
        self.assertNotIn('full_name', age_only)

    def test_tariff_snapshot_and_sequential_discounts(self):
        self.child.discount_percent = 10; self.child.save()
        tariff = Tariff.objects.create(name='8 занятий', sessions_total=8, price=5000, duration_days=30)
        data={'child':self.child.pk,'tariff':tariff.pk,'start_date':self.today,'promo':'Сентябрь','promo_percent':'20','promo_end_date':self.today+timedelta(days=10),'is_active':'on'}
        form=SubscriptionForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        sub=form.save()
        self.assertEqual(sub.price, Decimal('3600'))
        self.assertEqual(sub.discount_percent,10)
        self.assertEqual(sub.end_date,self.today+timedelta(days=30))
        tariff.price=9000; tariff.save()
        form=SubscriptionForm(data, instance=sub)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.save().price,Decimal('3600'))

    def test_manual_values_are_preserved_and_invalid_percent_rejected(self):
        tariff=Tariff.objects.create(name='8',sessions_total=8,price=5000,duration_days=30)
        data={'child':self.child.pk,'tariff':tariff.pk,'start_date':self.today,'manual_override':'on','end_date':self.today+timedelta(days=7),'sessions_total':3,'price':'1234','is_active':'on'}
        form=SubscriptionForm(data)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.save().price,Decimal('1234'))
        form=SubscriptionForm({**data,'promo_percent':101})
        self.assertFalse(form.is_valid())

    def test_invalid_subscription_form_remains_open(self):
        page=self.client.post(reverse('payments'), {'action':'save_subscription','subscription-child':self.child.pk,'subscription-start_date':self.today})
        self.assertEqual(page.status_code,200)
        self.assertTrue(page.context['subscription_form'].errors)
        self.assertContains(page,'id="subscription-modal" class="modal open')

    def test_debt_notification_resolves_after_payment_even_when_read(self):
        self.subscription(end_date=self.today-timedelta(days=1))
        sync_subscription_notifications(self.user)
        notice=Notification.objects.get(kind=Notification.Kind.SUBSCRIPTION_DEBT)
        notice.read_at=timezone.now(); notice.save()
        Payment.objects.create(child=self.child,amount=5000)
        sync_subscription_notifications(self.user)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        page=self.client.get(reverse('notifications'))
        self.assertEqual(page.context['debt_count'],0)

    def test_today_trial_notice_resolves_and_reopens(self):
        newcomer=Newcomer.objects.create(full_name='Пробная', trial_at=timezone.now())
        sync_today_trials(self.user)
        notice=Notification.objects.get(event_key__startswith='trial_today:')
        newcomer.attended=True; newcomer.save()
        sync_today_trials(self.user); notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        newcomer.attended=False; newcomer.save()
        sync_today_trials(self.user); notice.refresh_from_db()
        self.assertIsNone(notice.resolved_at)

    def test_camp_roster_is_idempotent_and_card_has_history(self):
        data={'name':'Летние сборы','kind':'training','start_date':self.today,'end_date':self.today+timedelta(days=7),'children':[self.child.pk]}
        self.assertEqual(self.client.post(reverse('camps'),data).status_code,302)
        camp=Camp.objects.get()
        self.client.post(reverse('camps')+f'?edit={camp.pk}',data)
        self.assertEqual(CampStay.objects.count(),1)
        self.assertContains(self.client.get(reverse('child_card',args=[self.child.pk])),'Летние сборы')

    def test_camp_legacy_multiple_stays_cannot_be_collapsed(self):
        camp=Camp.objects.create(name='Старый лагерь')
        for offset in (10,30):
            CampStay.objects.create(child=self.child,camp=camp,start_date=self.today-timedelta(days=offset),end_date=self.today-timedelta(days=offset-5))
        response=self.client.post(reverse('camps')+f'?edit={camp.pk}',{'name':camp.name,'kind':'camp','start_date':self.today,'end_date':self.today+timedelta(days=7),'children':[self.child.pk]})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(CampStay.objects.values('start_date').distinct().count(),2)

    def test_competition_document_upload_and_authenticated_download(self):
        competition=Competition.objects.create(name='Первенство',date=self.today)
        CompetitionEntry.objects.create(child=self.child,competition=competition)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response=self.client.post(reverse('competitions'),{'action':'upload_document','competition_id':competition.pk,'title':'Грамота','child':self.child.pk,'file':SimpleUploadedFile('award.pdf',b'%PDF-1.4\nTest')})
            self.assertEqual(response.status_code,302)
            document=CompetitionDocument.objects.get()
            response=self.client.get(reverse('competition_document_download',args=[document.pk]))
            self.assertEqual(b''.join(response.streaming_content),b'%PDF-1.4\nTest')
            self.assertIn('attachment',response['Content-Disposition'])
            self.client.logout()
            self.assertEqual(self.client.get(reverse('competition_document_download',args=[document.pk])).status_code,302)

    def test_new_pages_and_modal_forms_render(self):
        for name,query in [('group_list','?create=1'),('group_list',f'?edit={self.group.pk}'),('trainer_list','?create=1'),('trainer_list',f'?edit={self.trainer.pk}'),('camps','?create=1'),('payments',f'?child={self.child.pk}&new_subscription=1')]:
            with self.subTest(name=name,query=query):
                self.assertEqual(self.client.get(reverse(name)+query).status_code,200)
        page=self.client.get(reverse('child_card',args=[self.child.pk]))
        self.assertContains(page,'Посещения за 3 месяца')
        self.assertContains(page,'<th>Неделя</th>')
        days=[day for week in page.context['weeks'] for day in week['days'] if day]
        self.assertEqual(len(days),90)

    def test_invalid_inline_child_edit_stays_in_card(self):
        page=self.client.post(reverse('child_edit',args=[self.child.pk]), {'inline':'1','last_name':'Новая'})
        self.assertEqual(page.status_code,200)
        self.assertTemplateUsed(page,'crm/child_card.html')
        self.assertTrue(page.context['child_form'].errors)
        self.child.refresh_from_db(); self.assertEqual(self.child.last_name,'Тестовая')

    def test_group_schedule_formset_saves_from_modal(self):
        from .forms import ScheduleSlotFormSet
        prefix=ScheduleSlotFormSet().prefix
        response=self.client.post(reverse('group_list')+'?create=1',{'name':'Новая группа','trainer':self.trainer.pk,'salary_rate':'100','is_active':'on',f'{prefix}-TOTAL_FORMS':'1',f'{prefix}-INITIAL_FORMS':'0',f'{prefix}-MIN_NUM_FORMS':'0',f'{prefix}-MAX_NUM_FORMS':'1000',f'{prefix}-0-weekday':'4',f'{prefix}-0-start_time':'15:00',f'{prefix}-0-duration_minutes':'60'})
        self.assertEqual(response.status_code,302)
        group=Group.objects.get(name='Новая группа')
        self.assertEqual(group.schedule.get().weekday,4)

    def test_forecast_queries_do_not_grow_per_child(self):
        self.subscription()
        start=self.today.replace(day=1); end=start+timedelta(days=31)
        with CaptureQueriesContext(connection) as one:
            build_renewal_rows(start,end)
        for i in range(12):
            child=Child.objects.create(last_name=f'Тест{i}',first_name='Анна',birth_year=2016,group=self.group)
            self.subscription(child=child)
        with CaptureQueriesContext(connection) as many:
            build_renewal_rows(start,end)
        self.assertLessEqual(len(many), len(one)+1)

    def test_group_statistics_queries_do_not_grow_per_group(self):
        start=self.today.replace(day=1); end=start+timedelta(days=31)
        with CaptureQueriesContext(connection) as one:
            build_group_stats(start,end,self.today)
        for i in range(12):
            Group.objects.create(name=f'Группа{i}',trainer=self.trainer)
        with CaptureQueriesContext(connection) as many:
            build_group_stats(start,end,self.today)
        self.assertEqual(len(one),len(many))

    def test_editing_subscription_keeps_initial_child_and_start(self):
        subscription=self.subscription()
        response=self.client.get(reverse('payments'), {'edit_subscription':subscription.pk})
        form=response.context['subscription_form']
        self.assertEqual(form['child'].value(), self.child.pk)
        self.assertEqual(form['start_date'].value(), subscription.start_date)

    def test_future_subscription_does_not_disable_current(self):
        current=self.subscription()
        tariff=Tariff.objects.create(name='Следующий',price=5000,sessions_total=8,duration_days=30)
        self.client.post(reverse('payments'), {'action':'save_subscription','subscription-child':self.child.pk,'subscription-tariff':tariff.pk,'subscription-start_date':current.end_date+timedelta(days=1),'subscription-is_active':'on'})
        current.refresh_from_db()
        self.assertTrue(current.is_active)
        self.assertEqual(self.child.active_subscription().pk,current.pk)

    def test_bad_payment_is_rejected_without_crashing_or_writing(self):
        for amount,day in [('NaN',self.today),('Infinity',self.today),('123','not-a-date'),('-1',self.today)]:
            with self.subTest(amount=amount,day=day):
                response=self.client.post(reverse('payments'),{'action':'payment','child_id':self.child.pk,'amount':amount,'date':day})
                self.assertEqual(response.status_code,302)
        self.assertFalse(self.child.payments.exists())

    def test_intake_post_requires_login_before_resolving_edit_target(self):
        self.client.logout()
        response=self.client.post(reverse('newcomers'),{'action':'convert','newcomer_id':9999})
        self.assertEqual(response.status_code,302)
        self.assertIn('/login/',response.url)
