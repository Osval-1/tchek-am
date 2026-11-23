from django.contrib import admin

from .models import AICallLog


@admin.register(AICallLog)
class AICallLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "purpose",
        "model",
        "prompt_version",
        "success",
        "error",
        "tokens_in",
        "tokens_out",
        "cache_read_tokens",
        "latency_ms",
    )
    list_filter = ("purpose", "model", "success")
    readonly_fields = [f.name for f in AICallLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
