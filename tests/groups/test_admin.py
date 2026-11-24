from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from tchekam.core.models import AuditLog
from tchekam.groups.models import GroupOptOut, PartnerGroup, UnconsentedGroupLeave
from tchekam.identifiers.models import get_or_create_phone
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting

from ..imaging.helpers import encode, structured_image
from .conftest import GROUP_JID

pytestmark = pytest.mark.django_db

ADD = reverse("admin:groups_partnergroup_add")
CHANGELIST = reverse("admin:groups_partnergroup_changelist")


@pytest.fixture
def root():
    return get_user_model().objects.create_superuser("root", password="x")


@pytest.fixture
def client_su(client, otp_login, root):
    otp_login(client, root)
    return client


def form(**overrides):
    when = timezone.localtime() - timedelta(days=1)
    data = {
        "group_jid": GROUP_JID,
        "name": "Marché Mokolo",
        "admin_phone": "677 12 34 56",
        "consent_at_0": when.strftime("%Y-%m-%d"),
        "consent_at_1": when.strftime("%H:%M:%S"),
        "status": "active",
        "notice_confirmed": "on",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_recording_consent_sets_recorder_notice_time_and_audits(client_su, root):
    resp = client_su.post(ADD, form())

    assert resp.status_code == 302, resp.content
    group = PartnerGroup.objects.get()
    assert group.consent_recorded_by == root
    assert group.notice_confirmed_at is not None
    assert group.admin_phone == "+237677123456"
    entry = AuditLog.objects.get(action="groups.partner_group.created")
    assert entry.actor == root
    assert entry.object_id == str(group.pk)
    assert "677" not in str(entry.metadata)


def test_consent_needs_the_notice_confirmation(client_su):
    resp = client_su.post(ADD, form(notice_confirmed=None))

    assert resp.status_code == 200
    assert not PartnerGroup.objects.exists()
    assert not AuditLog.objects.filter(action__startswith="groups.").exists()


@pytest.mark.parametrize(
    "bad",
    [
        {"group_jid": "237670000001@s.whatsapp.net"},
        {"admin_phone": "hello"},
        {"consent_at_0": (timezone.localdate() + timedelta(days=3)).isoformat()},
    ],
)
def test_invalid_consent_is_refused(client_su, bad):
    resp = client_su.post(ADD, form(**bad))

    assert resp.status_code == 200
    assert not PartnerGroup.objects.exists()


def test_status_change_is_audited_and_consent_fields_are_locked(
    client_su, make_partner_group, root
):
    group = make_partner_group(GROUP_JID)
    ma = admin.site._registry[PartnerGroup]
    assert {"group_jid", "consent_at", "consent_recorded_by", "notice_confirmed_at"} <= set(
        ma.get_readonly_fields(None, group)
    )
    url = reverse("admin:groups_partnergroup_change", args=[group.pk])

    data = {"name": group.name, "admin_phone": group.admin_phone, "status": "paused"}
    resp = client_su.post(url, data)

    assert resp.status_code == 302, resp.content
    group.refresh_from_db()
    assert group.status == "paused"
    entry = AuditLog.objects.get(action="groups.partner_group.changed")
    assert entry.metadata == {"fields": ["status"]}
    assert entry.actor == root


def test_plain_delete_is_disabled(make_partner_group):
    ma = admin.site._registry[PartnerGroup]

    assert not ma.has_delete_permission(None)


def test_delete_with_sightings_action_erases_group_data_and_audits(
    client_su, make_partner_group, object_store, django_capture_on_commit_callbacks
):
    group = make_partner_group(GROUP_JID)
    other = make_partner_group()
    phone = get_or_create_phone("+237670000003")
    image = ingest(
        encode(structured_image(1)), "group", SightingContext("group", phone, group=group)
    )
    kept = ingest(
        encode(structured_image(2)), "group", SightingContext("group", phone, group=other)
    )

    with django_capture_on_commit_callbacks(execute=True):
        resp = client_su.post(
            CHANGELIST,
            {"action": "delete_with_sightings", "_selected_action": [group.pk]},
        )

    assert resp.status_code == 302
    assert list(PartnerGroup.objects.all()) == [other]
    assert list(Image.objects.all()) == [kept]
    assert ImageSighting.objects.get().group == other
    assert not object_store.exists(image.thumbnail_key)
    entry = AuditLog.objects.get(action="groups.partner_group.deleted")
    assert entry.metadata == {"sightings": 1, "images": 1}
    assert entry.object_id == str(group.pk)


def test_refresh_metadata_action_uses_the_daily_cache(client_su, make_partner_group, fake_channel):
    group = make_partner_group(GROUP_JID)
    fake_channel.groups[GROUP_JID] = {"subject": "Marché Mokolo", "participants": []}
    data = {"action": "refresh_metadata", "_selected_action": [group.pk]}

    client_su.post(CHANGELIST, data)
    client_su.post(CHANGELIST, data)

    assert fake_channel.metadata_calls == [GROUP_JID]
    page = client_su.get(reverse("admin:groups_partnergroup_change", args=[group.pk]))
    assert "Marché Mokolo" in page.content.decode()


@pytest.mark.parametrize("model", [PartnerGroup, UnconsentedGroupLeave, GroupOptOut])
def test_changelists_load(client_su, model):
    url = reverse(f"admin:groups_{model._meta.model_name}_changelist")

    assert client_su.get(url).status_code == 200


@pytest.mark.parametrize("model", [UnconsentedGroupLeave, GroupOptOut])
def test_logs_are_read_only(model):
    ma = admin.site._registry[model]

    assert not ma.has_add_permission(None)
    assert not ma.has_change_permission(None)
    assert not ma.has_delete_permission(None)


def test_anonymous_and_non_otp_staff_cannot_reach_the_admin(client):
    staff = get_user_model().objects.create_user("staff", password="x", is_staff=True)

    assert client.get(ADD).status_code == 302
    client.force_login(staff)  # password only: no verified OTP device
    resp = client.get(ADD)
    assert resp.status_code == 302
    assert resp["Location"].startswith(reverse("admin:login"))


def test_non_staff_with_otp_cannot_reach_the_admin(client, otp_login):
    otp_login(client, get_user_model().objects.create_user("plain", password="x"))

    resp = client.get(ADD)

    assert resp.status_code == 302
    assert resp["Location"].startswith(reverse("admin:login"))
