from django.contrib import admin

from .models import AgentControl, AICallLog


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


@admin.register(AgentControl)
class AgentControlAdmin(admin.ModelAdmin):
    list_display = ("id", "enabled", "vision_enabled", "rollout_percentage")
    filter_horizontal = ("pilot_users",)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser and not AgentControl.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from tchekam.core.audit import audit

        audit(
            request.user,
            "agent.control",
            obj,
            enabled=obj.enabled,
            vision_enabled=obj.vision_enabled,
            percentage=obj.rollout_percentage,
        )
