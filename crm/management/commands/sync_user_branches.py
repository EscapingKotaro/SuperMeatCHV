from django.core.management.base import BaseCommand

from crm.models import Role, StaffProfile, User


class Command(BaseCommand):
    help = "Переносит филиал из User.branch в StaffProfile.branch"

    def handle(self, *args, **options):
        copied = 0
        already_ok = 0
        conflicts = 0
        created_profiles = 0

        for user in User.objects.select_related("branch").all():
            profile, created = StaffProfile.objects.get_or_create(
                user=user,
                defaults={
                    "role": Role.MANAGER,
                    "branch": user.branch,
                },
            )

            if created:
                created_profiles += 1
                if user.branch_id:
                    copied += 1
                continue

            if not user.branch_id:
                already_ok += 1
                continue

            if not profile.branch_id:
                profile.branch = user.branch
                profile.save(update_fields=["branch"])
                copied += 1
                continue

            if profile.branch_id == user.branch_id:
                already_ok += 1
                continue

            conflicts += 1
            self.stdout.write(self.style.WARNING(
                f"Конфликт: {user.username}: "
                f"User.branch={user.branch}, "
                f"StaffProfile.branch={profile.branch}"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Перенесено: {copied}; "
            f"уже совпадало: {already_ok}; "
            f"создано профилей: {created_profiles}; "
            f"конфликтов: {conflicts}."
        ))