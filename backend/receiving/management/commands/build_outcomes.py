import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections

from receiving.outcomes import build_outcomes, submit_samples, to_json
from receiving.seed import load_reference_data


@contextmanager
def fresh_database() -> Iterator[None]:
    """Point the default connection at a new, migrated SQLite file for the duration.

    The dev database (and whatever staff did in the UI) is never touched.
    """
    connection = connections[DEFAULT_DB_ALIAS]
    original = connection.settings_dict["NAME"]
    with tempfile.TemporaryDirectory() as tmp:
        connection.close()
        connection.settings_dict["NAME"] = str(Path(tmp) / "outcomes.sqlite3")
        try:
            call_command("migrate", interactive=False, verbosity=0)
            yield
        finally:
            connection.close()
            connection.settings_dict["NAME"] = original


class Command(BaseCommand):
    """manage.py build_outcomes [--output PATH]"""

    help = "Load data/, submit the 12 sample invoices with no human review, write results/outcomes.json."

    def add_arguments(self, parser):
        """Command-line options."""
        parser.add_argument("--output", type=Path, default=None, help="Defaults to <RESULTS_DIR>/outcomes.json.")

    def handle(self, *args, output: Path | None, **options):
        """Run the whole pipeline on a fresh database and write the result."""
        output = output or settings.RESULTS_DIR / "outcomes.json"
        with fresh_database():
            load_reference_data(settings.DATA_DIR)
            results = submit_samples(settings.DATA_DIR)
            text = to_json(build_outcomes())
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        for result in results:
            self.stdout.write(f"{result.invoice.source_filename}: {result.invoice.status}")
        self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))
