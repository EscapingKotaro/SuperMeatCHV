from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from crm.context_processors import sync_subscription_notifications
from crm.models import ManagerTask, Newcomer, Notification


class Command(BaseCommand):
    help = "Создаёт недостающие уведомления для старых актуальных данных"

    def handle(self, *args, **options):
        users = list(
            get_user_model().objects
            .filter(is_active=True, is_staff=True)
        )

        task_created = 0
        trial_created = 0

        # Старые открытые задачи
        for task in ManagerTask.objects.filter(is_done=False).select_related("created_by"):
            if task.assignee_id:
                recipients = [u for u in users if u.pk == task.assignee_id]
            else:
                recipients = users

            for user in recipients:
                # Если пользователь уже получал любое уведомление по этой задаче,
                # второй раз её в историю не добавляем.
                if Notification.objects.filter(
                    recipient=user,
                    task=task,
                ).exists():
                    continue

                notification = Notification.objects.create(
                    recipient=user,
                    actor=task.created_by,
                    task=task,
                    kind=Notification.Kind.TASK_CREATED,
                    message=f"Задача «{task.title}»",
                    event_key=f"backfill:task:{task.pk}",
                )

                # Не притворяемся, что старая задача появилась сегодня.
                Notification.objects.filter(pk=notification.pk).update(
                    created_at=task.created_at,
                )

                task_created += 1

        # Старые необработанные пробные
        newcomers = Newcomer.objects.filter(
            trial_at__isnull=False,
            attended=False,
            lesson_cancelled=False,
            child__isnull=True,
        )

        for newcomer in newcomers:
            trial_at = timezone.localtime(newcomer.trial_at)
            url = f"{reverse('newcomers')}?edit={newcomer.pk}"

            for user in users:
                if Notification.objects.filter(
                    recipient=user,
                    kind=Notification.Kind.TRIAL_SCHEDULED,
                    url=url,
                ).exists():
                    continue

                notification = Notification.objects.create(
                    recipient=user,
                    kind=Notification.Kind.TRIAL_SCHEDULED,
                    message=(
                        f"Пробное: {newcomer.full_name} · "
                        f"{trial_at:%d.%m.%Y %H:%M}"
                    ),
                    url=url,
                    event_key=f"backfill:trial:{newcomer.pk}",
                )

                Notification.objects.filter(pk=notification.pk).update(
                    created_at=newcomer.created_at,
                )

                trial_created += 1

        # Текущие заканчивающиеся абонементы
        for user in users:
            sync_subscription_notifications(user)

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Задачи: {task_created}, "
            f"пробные: {trial_created}, "
            "абонементы синхронизированы."
        ))