from django.contrib import admin

from .models import AccountName, PhoneNumber


@admin.register(PhoneNumber)
class PhoneNumberAdmin(admin.ModelAdmin):
    list_display = ("e164", "operator", "first_seen", "check_count")
    list_filter = ("operator",)
    search_fields = ("e164",)


@admin.register(AccountName)
class AccountNameAdmin(admin.ModelAdmin):
    list_display = ("display_raw", "normalized", "provider", "created_at")
    list_filter = ("provider",)
    search_fields = ("normalized",)
