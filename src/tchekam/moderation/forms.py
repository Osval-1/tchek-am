"""Validation for the moderator POSTs. Pure input checks; state rules live in service."""

from datetime import date

from django import forms
from django.utils import timezone

from tchekam.identifiers.models import AccountName
from tchekam.identifiers.names import normalize_name
from tchekam.identifiers.phone import normalize_cm_number
from tchekam.reports.models import Report

REJECT_REASONS = [
    ("insufficient_evidence", "Insufficient evidence"),
    ("duplicate", "Duplicate"),
    ("not_a_scam", "Not a scam"),
    ("cannot_verify", "Cannot verify"),
    ("abusive_or_false", "Abusive or false report"),
    ("other", "Other (explain below)"),
]
MAX_TEXT = 500
MAX_NAME_LEN = 255
EARLIEST_INCIDENT = date(2000, 1, 1)
DECISION_ACTIONS = ["approve", "reject", "need_info", "merge", "reopen"]


class EditForm(forms.Form):
    has_payment_proof = forms.BooleanField(required=False)
    scam_type = forms.ChoiceField(
        choices=[("", "---------"), *Report.ScamType.choices], required=False
    )
    incident_date = forms.DateField(required=False)
    amount_xaf = forms.IntegerField(required=False, min_value=1, max_value=2_000_000_000)
    summary_final = forms.CharField(required=False, max_length=2000)
    add_phone = forms.CharField(required=False, max_length=40)
    add_name = forms.CharField(required=False, max_length=255)
    add_name_provider = forms.ChoiceField(
        choices=AccountName.Provider.choices, required=False, initial="unknown"
    )

    def clean_incident_date(self):
        value = self.cleaned_data["incident_date"]
        if value is not None and value > timezone.localdate():
            raise forms.ValidationError("The incident date cannot be in the future.")
        if value is not None and value < EARLIEST_INCIDENT:
            raise forms.ValidationError("The incident date is implausibly old.")
        return value

    def clean_add_phone(self):
        raw = self.cleaned_data["add_phone"].strip()
        if not raw:
            return ""
        e164 = normalize_cm_number(raw)
        if e164 is None:
            raise forms.ValidationError("Not a valid Cameroonian phone number.")
        return e164

    def clean_add_name(self):
        raw = " ".join(self.cleaned_data["add_name"].split())
        if not raw:
            return ""
        normalized = normalize_name(raw)
        if not normalized:
            raise forms.ValidationError("Enter a payee name with at least one letter or digit.")
        if len(normalized) > MAX_NAME_LEN:  # NFKD can expand, and the column is 255 wide
            raise forms.ValidationError("The payee name is too long.")
        return raw

    def clean_add_name_provider(self):
        return self.cleaned_data["add_name_provider"] or AccountName.Provider.UNKNOWN


class DecisionForm(forms.Form):
    action = forms.ChoiceField(choices=[(a, a) for a in DECISION_ACTIONS])
    reason_code = forms.ChoiceField(choices=REJECT_REASONS, required=False)
    reason_text = forms.CharField(required=False, max_length=MAX_TEXT)
    message = forms.CharField(required=False, max_length=MAX_TEXT)
    merge_target = forms.IntegerField(required=False, min_value=1)
    reopen_reason = forms.CharField(required=False, max_length=MAX_TEXT)

    def clean(self):
        data = super().clean()
        action = data.get("action")
        if action == "reject":
            if not data.get("reason_code"):
                self.add_error("reason_code", "Choose a rejection reason.")
            elif data["reason_code"] == "other" and not data.get("reason_text", "").strip():
                self.add_error("reason_text", "Explain the reason when choosing 'Other'.")
        elif action == "need_info" and not data.get("message", "").strip():
            self.add_error("message", "Write the question for the reporter.")
        elif action == "merge" and not data.get("merge_target"):
            self.add_error("merge_target", "Enter the id of the report to merge into.")
        elif action == "reopen" and not data.get("reopen_reason", "").strip():
            self.add_error("reopen_reason", "A reason is required to reopen a report.")
        return data

    def reason(self) -> str:
        """The text stored in ModerationDecision.reason for the chosen action."""
        d = self.cleaned_data
        match d["action"]:
            case "reject":
                text = d["reason_text"].strip()
                return f"{d['reason_code']}: {text}" if text else d["reason_code"]
            case "need_info":
                return d["message"].strip()
            case "reopen":
                return d["reopen_reason"].strip()
            case "merge":
                return f"merged into {d['merge_target']}"
        return ""


def error_messages(form: forms.Form) -> list[str]:
    return [f"{msg}" for errors in form.errors.values() for msg in errors]
