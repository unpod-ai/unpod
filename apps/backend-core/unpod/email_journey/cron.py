from django_cron import CronJobBase, Schedule

from unpod.email_journey.services import process_due_journeys


class EmailJourneyCronJob(CronJobBase):
    RUN_EVERY_MINS = 60

    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = "email_journey_EmailJourneyCronJob"  # a unique code

    def do(self):
        return process_due_journeys()
