from django.db import models

from tchekam.conversations.models import BotUser


class CheckLog(models.Model):
    class Kind(models.TextChoices):
        NUMBER = "number"
        IMAGE = "image"
        MESSAGE = "message"
        NAME = "name"

    class Band(models.TextChoices):
        GREEN = "green"
        YELLOW = "yellow"
        ORANGE = "orange"
        RED = "red"
        NONE = "none"

    # SET_NULL: erasing a user must not delete the aggregate check history.
    user = models.ForeignKey(BotUser, null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    subject_ref = models.CharField(max_length=64)  # E.164 or image sha256
    result_band = models.CharField(max_length=10, choices=Band.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self) -> str:
        # subject_ref may be a phone number, so it stays out of the string
        return f"CheckLog#{self.pk} ({self.kind}, {self.result_band})"
