from django.contrib import admin

from tchekam.retention.hold import LegalHoldAdminMixin

from .models import AccountName, PhoneNumber


@admin.register(PhoneNumber)
class PhoneNumberAdmin(LegalHoldAdminMixin, admin.ModelAdmin):
    list_display = ("e164", "operator", "first_seen", "check_count", "legal_hold")
    list_filter = ("operator", "legal_hold")
    search_fields = ("e164",)
    # Changes only through the audited legal-hold actions.
    readonly_fields = ("legal_hold",)


@admin.register(AccountName)
class AccountNameAdmin(admin.ModelAdmin):
    list_display = ("display_raw", "normalized", "provider", "created_at")
    list_filter = ("provider",)
    search_fields = ("normalized",)
