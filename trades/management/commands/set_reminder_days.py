from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from trades.daylists import days_after_to_days_left, parse_day_list
from trades.models import ReminderSchedule


class Command(BaseCommand):
    help = (
        "Set the site-wide reminder days as DAYS LEFT before each account's "
        "inactivity deadline (0 = the deadline day). Accepts multiple values "
        "separated by commas and/or spaces. Examples: 20 15 5 3 1 0  |  "
        "20,10,3,1,0. Users and accounts can override this."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "days",
            nargs="*",
            # Left as strings (not type=int) so a stray non-numeric CLI
            # argument is skipped with a warning instead of argparse
            # rejecting the whole command outright.
            type=str,
            help="Days-left values. If omitted, you will be prompted to type them in.",
        )
        parser.add_argument(
            "--days-after",
            action="store_true",
            help="Interpret the values the old way, as days SINCE the last trade "
            "for a 30-day limit (e.g. 10 15 25 30), and convert them.",
        )

    def handle(self, *args, **options):
        current = ReminderSchedule.get().days_left_list()
        self.stdout.write("Current reminder days (days left): " + ", ".join(map(str, current)))

        days_input = options["days"]
        if not days_input:
            raw = input(
                "Enter reminder days as DAYS LEFT before the deadline "
                "(comma/space separated, 0 = deadline day, e.g. '20 15 5 3 1 0'): "
            )
            days_input = [raw]

        days, invalid = parse_day_list(days_input)
        for token in invalid:
            self.stdout.write(self.style.WARNING(f"  skipping non-numeric value: '{token}'"))
        if options["days_after"]:
            days = days_after_to_days_left(days)

        if not days:
            self.stderr.write(self.style.ERROR("No valid days parsed. Aborting."))
            return

        schedule = ReminderSchedule.get()
        schedule.days_left = days
        try:
            schedule.full_clean()  # runs the model validators
        except ValidationError as e:
            self.stderr.write(self.style.ERROR(f"Invalid days: {e.messages}"))
            return

        schedule.save()  # get() may return an unsaved default, so save() persists it

        self.stdout.write(
            self.style.SUCCESS("Reminder days set to (days left): " + ", ".join(map(str, days)))
        )
        self.stdout.write(
            "For a 30-day account that is days "
            + ", ".join(str(30 - d) for d in sorted(days, reverse=True) if d <= 30)
            + " after the last trade."
        )
