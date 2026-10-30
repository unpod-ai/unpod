from django.urls import path

from unpod.email_journey.views import JourneyUnsubscribeView

urlpatterns = [
    path("unsubscribe/<str:token>/", JourneyUnsubscribeView.as_view(), name="email-journey-unsubscribe"),
]
