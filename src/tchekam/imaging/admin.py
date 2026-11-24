from django.contrib import admin

from .models import Image, ImageSighting


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Image)
class ImageAdmin(ReadOnlyAdmin):
    list_display = ("id", "sha256", "source", "first_seen")
    readonly_fields = ("sha256", "created_at")


@admin.register(ImageSighting)
class ImageSightingAdmin(ReadOnlyAdmin):
    # group is left out: group identity must not leak through this view.
    list_display = ("id", "image", "phone_number", "context", "seen_at")
    exclude = ("group",)
