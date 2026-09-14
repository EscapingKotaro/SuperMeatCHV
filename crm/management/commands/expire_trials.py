from django.core.management.base import BaseCommand
from crm.models import expire_trials

class Command(BaseCommand):
    help = "Перевести неоплаченных пробников через 30 дней без оплаты в архив"

    def handle(self, *args, **options):
        self.stdout.write(f"Переведено в архив: {expire_trials()}")
