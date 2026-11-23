from django.contrib import admin

from .models import CheckLog


@admin.register(CheckLog)
class CheckLogAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "result_band", "created_at")
    list_filter = ("kind", "result_band")
    raw_id_fields = ("user",)
