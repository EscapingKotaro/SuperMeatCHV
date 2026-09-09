from django.core.management.base import BaseCommand
from crm.models import expire_trials

class Command(BaseCommand):
    help = "Перевести неоплаченных пробников старше 14 дней в потерянные"

    def handle(self, *args, **options):
        self.stdout.write(f"Переведено в потерянные: {expire_trials()}")
