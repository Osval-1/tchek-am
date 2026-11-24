from django.contrib import admin

from tchekam.retention.hold import LegalHoldAdminMixin

from .models import Evidence, ModerationDecision, Report, ReportLink, ReportSubject


@admin.register(Report)
class ReportAdmin(LegalHoldAdminMixin, admin.ModelAdmin):
    list_display = ("id", "reference", "status", "scam_type", "submitted_at", "legal_hold")
    list_filter = ("status", "scam_type", "legal_hold")
    # Status changes go through Report.transition (review page, Issue 13), never a form edit.
    readonly_fields = (
        "status",
        "merged_into",
        "submitted_at",
        "decided_at",
        "incident_date",
        "reference",
        "reporter",
        "created_at",
        "last_activity_at",
        "legal_hold",
        "has_payment_proof",
        "evidence_score",
    )
    # Those change only via the review page (Issue 13) or the audited legal-hold toggle (Issue 24).
    raw_id_fields = ("reporter", "merged_into")

    def has_delete_permission(self, request, obj=None):
        return False  # deletion only via retention jobs


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "kind", "mimetype", "size_bytes", "created_at")
    list_filter = ("kind",)
    raw_id_fields = ("report",)
    exclude = ("object_key",)  # storage key stays out of the UI; no download from admin
    readonly_fields = (
        "report",
        "kind",
        "mimetype",
        "sha256",
        "size_bytes",
        "transcript",
        "transcript_confidence",
        "ai_extraction",
        "tamper_flags",
        "training_opt_in",
        "legal_hold",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # deletion only via retention jobs


@admin.register(ReportSubject)
class ReportSubjectAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "role", "source", "confirmed")
    list_filter = ("role", "source", "confirmed")
    raw_id_fields = ("report", "phone_number", "account_name", "image")


@admin.register(ReportLink)
class ReportLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "report_a", "report_b", "reason", "score")
    list_filter = ("reason",)
    raw_id_fields = ("report_a", "report_b")


@admin.register(ModerationDecision)
class ModerationDecisionAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "moderator", "action", "created_at")
    list_filter = ("action",)
    raw_id_fields = ("report", "moderator")
    readonly_fields = ("report", "moderator", "action", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
