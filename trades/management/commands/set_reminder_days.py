from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError

from trades.models import ReminderSchedule


class Command(BaseCommand):
    help = (
        "Interactively set the reminder day numbers (days after last trade). "
        "Accepts multiple values separated by commas and/or spaces. "
        "Examples: 10 15 25 30    |    10,15,25,26,27,28,29,30"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "days",
            nargs="*",
            type=int,
            help="Optional day numbers given on the command line. "
                 "If omitted, you will be prompted to type them in.",
        )

    def _parse_days(self, values):
        """Flatten CLI ints and prompted tokens into a list of ints.

        Non-numeric tokens are skipped with a warning (so a stray word in
        keyboard input doesn't crash the command).
        """
        parsed = []
        for value in values:
            for part in str(value).replace(",", " ").split():
                if not part.strip():
                    continue
                try:
                    parsed.append(int(part))
                except (TypeError, ValueError):
                    self.stdout.write(
                        self.style.WARNING(f"  skipping non-numeric value: '{part}'")
                    )
        return parsed

    def handle(self, *args, **options):
        days_input = options["days"]

        # Gather via keyboard prompt if nothing was given on the CLI.
        if not days_input:
            raw = input(
                "Enter reminder day numbers (comma/space separated, "
                "multiple allowed, e.g. '10 15 25 30'): "
            )
            days_input = raw.replace(",", " ").split()

        if not days_input:
            self.stderr.write(self.style.ERROR("No reminder days provided. Aborting."))
            return

        # Flatten (in case comma/space was mixed) and dedupe + sort.
        flat = self._parse_days(days_input)
        days = sorted(set(flat))

        if not days:
            self.stderr.write(self.style.ERROR("No valid days parsed. Aborting."))
            return

        schedule = ReminderSchedule.get()
        schedule.day_list = days
        try:
            schedule.full_clean()  # runs the model validators
        except ValidationError as e:
            self.stderr.write(self.style.ERROR(f"Invalid days: {e.messages}"))
            return

        schedule.save()  # get() may return an unsaved default, so save() persists it

        self.stdout.write(
            self.style.SUCCESS(
                "Reminder schedule set to: " + " ".join(str(d) for d in days)
            )
        )
        self.stdout.write(
            "Reminders will now fire on the following days after last trade:\n"
            + self.style.WARNING(", ".join(str(d) for d in days))
        )
