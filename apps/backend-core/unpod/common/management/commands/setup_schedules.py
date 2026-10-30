"""
Management command to set up Django-Q2 scheduled tasks
Replaces django_cron jobs with Django-Q2 schedules
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Set up Django-Q2 scheduled tasks (migrated from django_cron)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Setting up Django-Q2 schedules..."))

        schedules = [
            # Thread - Create Cron Posts (every 1 minute)
            {
                "name": "thread_create_cron_post",
                "func": "unpod.thread.tasks.create_cron_post",
                "schedule_type": Schedule.MINUTES,
                "minutes": 1,
                "repeats": -1,
            },
            # Core Components - Event Trigger (every 1 minute)
            {
                "name": "core_event_trigger_cron",
                "func": "unpod.core_components.tasks.event_trigger_cron",
                "schedule_type": Schedule.MINUTES,
                "minutes": 1,
                "repeats": -1,
            },
            # Email Journey - onboarding lifecycle emails (every 60 minutes)
            {
                "name": "email_journey_cron",
                "func": "unpod.email_journey.tasks.email_journey_cron",
                "schedule_type": Schedule.MINUTES,
                "minutes": 60,
                "repeats": -1,
            },
        ]

        created_count = 0
        updated_count = 0

        for schedule_data in schedules:
            name = schedule_data.pop("name")
            schedule, created = Schedule.objects.update_or_create(
                name=name, defaults=schedule_data
            )

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"✓ Created schedule: {name}"))
            else:
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f"✓ Updated schedule: {name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{created_count} schedules created, {updated_count} schedules updated"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "\nIMPORTANT: Start Django-Q2 cluster with: python manage.py qcluster"
            )
        )
