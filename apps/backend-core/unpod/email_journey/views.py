from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from unpod.common.renderers import UnpodJSONRenderer
from unpod.email_journey.services import unsubscribe_by_token


class JourneyUnsubscribeView(APIView):
    """Target of the unsubscribe link in every journey email (signed token, no login)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    renderer_classes = [UnpodJSONRenderer]

    def get(self, request, token, *args, **kwargs):
        journey = unsubscribe_by_token(token)
        if journey is None:
            return Response({"message": "Invalid or expired unsubscribe link"}, status=400)
        return Response(
            {"message": "You have been unsubscribed from onboarding emails"}, status=200
        )

    post = get  # RFC 8058 one-click unsubscribe
