"""Partner-group consent records (staff + OTP only, via the project's TchekAdminSite).

Every create, change and deletion is audit-logged (field names and counts, never values).
Consent fields are write-once. There is no plain delete: "Delete group and all its sightings"
erases the group's sightings (and their orphaned images) first, then the record.
"""

import re

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from tchekam.core.audit import audit
from tchekam.core.http import client_ip
from tchekam.identifiers.phone import normalize_cm_number
from tchekam.imaging.erase import delete_sightings
from tchekam.imaging.models import ImageSighting
from tchekam.messaging.channel import ChannelError, is_group_jid

from .metadata import group_metadata
from .models import GroupMetadata, GroupOptOut, PartnerGroup, UnconsentedGroupLeave

NOTICE = "This group is protected by Tchek-Am. Product photos are checked for reuse."
_INTERNATIONAL = re.compile(r"\+[1-9]\d{7,14}")
CONSENT_FIELDS = ("group_jid", "consent_at", "consent_recorded_by", "notice_confirmed_at")


class PartnerGroupForm(forms.ModelForm):
    notice_confirmed = forms.BooleanField(
        required=True,
        label="Notice confirmed",
        help_text=f'The group admin posted or approved the notice: "{NOTICE}"',
    )

    class Meta:
        model = PartnerGroup
        fields = ("group_jid", "name", "admin_phone", "consent_at", "status")

    def clean_group_jid(self):
        jid = self.cleaned_data["group_jid"].strip()
        if not is_group_jid(jid):
            raise forms.ValidationError("A group JID ends with @g.us.")
        return jid

    def clean_admin_phone(self):
        raw = self.cleaned_data["admin_phone"]
        e164 = normalize_cm_number(raw)
        if e164 is None:
            compact = re.sub(r"[\s.\-()]", "", raw)
            e164 = compact if _INTERNATIONAL.fullmatch(compact) else None
        if e164 is None:
            raise forms.ValidationError("Enter the admin's number, e.g. +237 6XX XX XX XX.")
        return e164

    def clean_consent_at(self):
        consent_at = self.cleaned_data["consent_at"]
        if consent_at > timezone.now():
            raise forms.ValidationError("Consent cannot be in the future.")
        return consent_at


class PartnerGroupChangeForm(forms.ModelForm):
    class Meta:
        model = PartnerGroup
        fields = ("name", "admin_phone", "status")

    clean_admin_phone = PartnerGroupForm.clean_admin_phone


@admin.register(PartnerGroup)
class PartnerGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "consent_at", "whatsapp_subject")
    list_filter = ("status",)
    search_fields = ("name",)
    actions = ("refresh_metadata", "delete_with_sightings")

    def get_form(self, request, obj=None, change=False, **kwargs):
        kwargs["form"] = PartnerGroupChangeForm if obj is not None else PartnerGroupForm
        return super().get_form(request, obj, change=change, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return (*PartnerGroupForm.Meta.fields, "notice_confirmed")
        return (*CONSENT_FIELDS, *PartnerGroupChangeForm.Meta.fields, "whatsapp_subject")

    def get_readonly_fields(self, request, obj=None):
        return (*CONSENT_FIELDS, "whatsapp_subject") if obj is not None else ()

    @admin.display(description="WhatsApp subject (cached)")
    def whatsapp_subject(self, obj):
        meta = GroupMetadata.objects.filter(group_jid=obj.group_jid).first()
        return meta.subject if meta and meta.fetched_at else "-"

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if not change:
                obj.consent_recorded_by = request.user
                obj.notice_confirmed_at = timezone.now()
            super().save_model(request, obj, form, change)
            if change:
                fields = [f for f in form.changed_data if f in PartnerGroupChangeForm.Meta.fields]
                audit(
                    request.user,
                    "groups.partner_group.changed",
                    obj,
                    ip=client_ip(request),
                    fields=fields,
                )
            else:
                audit(request.user, "groups.partner_group.created", obj, ip=client_ip(request))

    def has_delete_permission(self, request, obj=None):
        return False  # only through the audited delete_with_sightings action

    def has_erase_permission(self, request):
        return request.user.has_perm("groups.delete_partnergroup")

    @admin.action(description="Delete group and all its sightings", permissions=["erase"])
    def delete_with_sightings(self, request, queryset):
        groups = list(queryset)
        for group in groups:
            with transaction.atomic():
                erased = delete_sightings(ImageSighting.objects.filter(group=group))
                audit(
                    request.user,
                    "groups.partner_group.deleted",
                    group,
                    ip=client_ip(request),
                    sightings=erased.sightings,
                    images=erased.images,
                )
                group.delete()
        self.message_user(request, f"Deleted {len(groups)} group(s) and their sightings.")

    @admin.action(description="Refresh WhatsApp subject (at most once a day per group)")
    def refresh_metadata(self, request, queryset):
        for group in queryset:
            try:
                group_metadata(group.group_jid)
            except ChannelError as exc:
                self.message_user(request, f"{group}: {type(exc).__name__}", messages.WARNING)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UnconsentedGroupLeave)
class UnconsentedGroupLeaveAdmin(ReadOnlyAdmin):
    list_display = ("id", "group_jid", "left_at")


@admin.register(GroupOptOut)
class GroupOptOutAdmin(ReadOnlyAdmin):
    # Deleting an opt-out would silently resume collection, so it is never possible here.
    list_display = ("id", "created_at")
