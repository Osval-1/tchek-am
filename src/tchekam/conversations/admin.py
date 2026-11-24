from django.contrib import admin

from tchekam.retention.hold import LegalHoldAdminMixin

from .models import BotUser


@admin.register(BotUser)
class BotUserAdmin(LegalHoldAdminMixin, admin.ModelAdmin):
    """Users exist here only for the legal-hold toggle (ISSUES.md Issue 24).

    The phone number is never displayed (PII); an exact-number search finds a user when the
    police or a court names one. Nothing is editable: holds change only through the audited
    actions, and users are never deleted from the admin.
    """

    list_display = ("__str__", "language", "blocked", "legal_hold", "created_at")
    list_filter = ("legal_hold", "blocked")
    search_fields = ("=wa_phone",)
    fields = ("language", "blocked", "trust_weight", "legal_hold", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
