from django.contrib import admin

from unpod.email_journey.models import JourneyEmail, OrgEmailJourney


class ReadOnlyAdminMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class JourneyEmailInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = JourneyEmail
    extra = 0
    fields = ("email_key", "status", "reason", "attempts", "due_at", "sent_at", "modified")
    readonly_fields = fields
    ordering = ("due_at", "created")


@admin.register(OrgEmailJourney)
class OrgEmailJourneyAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "organization", "recipient", "product_id", "status",
                    "started_at", "unsubscribed_at", "last_processed_at")
    list_filter = ("status", "product_id")
    search_fields = ("organization__name", "organization__domain_handle", "recipient__email")
    raw_id_fields = ("organization", "recipient")
    inlines = [JourneyEmailInline]


@admin.register(JourneyEmail)
class JourneyEmailAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "journey", "email_key", "status", "reason", "attempts", "due_at", "sent_at")
    list_filter = ("status", "email_key")
    search_fields = ("journey__recipient__email", "journey__organization__name")
    raw_id_fields = ("journey",)
