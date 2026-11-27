from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from receiving.models import Product
from receiving.seed import SeedError, load_reference_data, wipe_all


class Command(BaseCommand):
    """manage.py seed_data [--reset]"""

    help = "Load reference data from data/ into an empty database. --reset wipes everything first."

    def add_arguments(self, parser):
        """Command-line options."""
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all receiving data (including invoices and stock movements) and reload.",
        )

    def handle(self, *args, reset: bool, **options):
        """Load data/ unless it is already loaded; --reset wipes everything first."""
        with transaction.atomic():
            if reset:
                wipe_all()
            elif Product.objects.exists():
                self.stdout.write("Reference data already loaded, nothing to do (use --reset to reload).")
                return
            try:
                counts = load_reference_data(settings.DATA_DIR)
            except SeedError as exc:
                raise CommandError(str(exc)) from exc
        summary = ", ".join(f"{count} {name}" for name, count in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Loaded {summary} from {settings.DATA_DIR}."))
