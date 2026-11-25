from django.db import models


class AICallLog(models.Model):
    """One row per LLM call, for cost and quality tracking.

    Never holds prompt or response content: only metadata about the call.
    """

    purpose = models.CharField(max_length=50, db_index=True)
    # The model that served the call, which may be a server-side fallback.
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField()
    # Exception class name, "invalid_output", "refusal:<category>" or "max_tokens".
    error = models.CharField(max_length=100, blank=True)
    request_id = models.CharField(max_length=100, blank=True)
    serving_provider = models.CharField(max_length=100, blank=True)
    agent_run = models.ForeignKey("AgentRun", on_delete=models.SET_NULL, null=True, blank=True)
    call_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "AI call log"

    def __str__(self):
        status = "ok" if self.success else self.error
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.purpose} {status}"


class AgentRecord(models.Model):
    class Meta:
        abstract = True

    def __str__(self):
        return f"{type(self).__name__}#{self.pk}"


class AgentControl(AgentRecord):
    """Runtime kill switch and explicit pilot cohort; no deployment needed to cancel."""

    enabled = models.BooleanField(default=False)
    vision_enabled = models.BooleanField(default=False)
    rollout_percentage = models.PositiveSmallIntegerField(default=0)
    pilot_users = models.ManyToManyField("conversations.BotUser", blank=True)


class AgentRun(AgentRecord):
    user = models.ForeignKey("conversations.BotUser", on_delete=models.CASCADE)
    inbound = models.OneToOneField("messaging.InboundEvent", on_delete=models.SET_NULL, null=True)
    inbound_key = models.CharField(max_length=255, unique=True)
    generation = models.PositiveBigIntegerField()
    sequence = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, default="pending", db_index=True)
    fence = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    model_calls = models.PositiveSmallIntegerField(default=0)
    tool_calls = models.PositiveSmallIntegerField(default=0)
    vision_calls = models.PositiveSmallIntegerField(default=0)
    stt_calls = models.PositiveSmallIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=40, blank=True)
    legal_hold = models.BooleanField(default=False)
    linked_report = models.ForeignKey("reports.Report", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "sequence"], name="agent_sequence")]
        indexes = [models.Index(fields=["user", "status", "sequence"])]


class AgentTurn(AgentRecord):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    user = models.ForeignKey("conversations.BotUser", on_delete=models.CASCADE)
    generation = models.PositiveBigIntegerField()
    role = models.CharField(max_length=12, choices=[("user", "user"), ("assistant", "assistant")])
    source = models.CharField(max_length=20)
    content = models.JSONField(default=dict)
    key_version = models.CharField(max_length=20)
    signature = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "role"], name="agent_run_role")]


class AgentEntityReference(AgentRecord):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    user = models.ForeignKey("conversations.BotUser", on_delete=models.CASCADE)
    generation = models.PositiveBigIntegerField()
    alias = models.CharField(max_length=40)
    value = models.CharField(max_length=40)
    key_version = models.CharField(max_length=20)
    signature = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "alias"], name="agent_run_alias")]


class AgentOperation(AgentRecord):
    """Idempotent side effects and mandatory local authorization audit."""

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    tool = models.CharField(max_length=40)
    outcome = models.CharField(max_length=40)
    # Only reviewed catalog/action codes. Raw tool results never persist here.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "key"], name="agent_operation")]


class AgentDelivery(AgentRecord):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    index = models.PositiveSmallIntegerField()
    generation = models.PositiveBigIntegerField()
    text = models.TextField()  # reviewed rendered reply; erased with run/history lifecycle
    status = models.CharField(max_length=16, default="pending", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "index"], name="agent_reply_index")]


class AgentBudget(AgentRecord):
    """Currency uses integer micro USD. Locks serialize all competing reservations."""

    scope = models.CharField(max_length=80, unique=True)
    used = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentReservation(AgentRecord):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    call_id = models.CharField(max_length=80, unique=True)
    amount = models.PositiveBigIntegerField()
    user_scope = models.CharField(max_length=80)
    global_scope = models.CharField(max_length=80)
    status = models.CharField(max_length=16, default="reserved")
    created_at = models.DateTimeField(auto_now_add=True)


class AIUsageMonthly(AgentRecord):
    month = models.DateField()
    purpose = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    calls = models.PositiveBigIntegerField(default=0)
    tokens_in = models.PositiveBigIntegerField(default=0)
    tokens_out = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["month", "purpose", "model"], name="ai_usage_month")
        ]
