"""
Django-Q2 task for the onboarding email journey (mirrors cron.EmailJourneyCronJob)
"""
from unpod.email_journey.services import process_due_journeys


def email_journey_cron():
    return process_due_journeys()
