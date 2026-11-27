from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from receiving.services import UploadRejected, ingest_file


class Command(BaseCommand):
    """manage.py ingest FILE [FILE ...]"""

    help = "Submit invoice files through the same pipeline as the API."

    def add_arguments(self, parser):
        """Command-line options."""
        parser.add_argument("paths", nargs="+", type=Path)

    def handle(self, *args, paths: list[Path], **options):
        """Ingest each file and print the outcome."""
        failed = False
        for path in paths:
            try:
                result = ingest_file(path.name, path.read_bytes())
            except (OSError, UploadRejected) as exc:
                self.stderr.write(f"{path}: not submitted: {exc}")
                failed = True
                continue
            invoice = result.invoice
            again = "" if result.created else " (already uploaded)"
            self.stdout.write(f"{path.name}: {invoice.status}{again}. {invoice.status_notes}")
        if failed:
            raise CommandError("Some files were not submitted.")
