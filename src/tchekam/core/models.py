from django.conf import settings
from django.db import models


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("AuditLog is append-only")

    def delete(self):
        raise RuntimeError("AuditLog is append-only")


class AuditLog(models.Model):
    # PROTECT: audit rows must outlive accountability questions, so a user with history
    # cannot be deleted (deactivate instead).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("AuditLog is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditLog is append-only")
