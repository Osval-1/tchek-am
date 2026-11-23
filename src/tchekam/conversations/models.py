from django.db import models


class BotUser(models.Model):
    """A WhatsApp user of the bot. PII table: wa_phone is the user's number."""

    class Language(models.TextChoices):
        FR = "fr", "Français"
        EN = "en", "English"
        PCM = "pcm", "Pidgin"

    wa_phone = models.CharField(max_length=20, unique=True)  # E.164
    language = models.CharField(max_length=3, choices=Language.choices, null=True, blank=True)  # noqa: DJ001  # NULL = not onboarded yet
    trust_weight = models.FloatField(default=1.0)
    blocked = models.BooleanField(default=False)
    training_opt_in = models.BooleanField(default=False)
    # The opt-in question is asked once; False here means "not decided yet", not "no".
    training_opt_in_asked = models.BooleanField(default=False)
    # Stamped on every inbound message; reminders and retention jobs key off it.
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"BotUser#{self.pk}"  # never the phone number: it ends up in logs and admin lists


class Conversation(models.Model):
    IDLE = "idle"

    user = models.OneToOneField(BotUser, on_delete=models.CASCADE, related_name="conversation")
    flow = models.CharField(max_length=40, default=IDLE)
    step = models.CharField(max_length=40, blank=True)
    state = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Conversation#{self.pk} ({self.flow})"

    def reset(self) -> None:
        """Back to idle with empty state. Does not save; the router saves once per message."""
        self.flow = self.IDLE
        self.step = ""
        self.state = {}
        self.expires_at = None
