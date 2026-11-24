import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from time import monotonic
from unittest.mock import patch

import pytest
from django.db import connections
from django.utils import timezone
from PIL import Image

from tchekam.ai.agent.budget import reserve
from tchekam.ai.agent.execution import claim
from tchekam.ai.agent.graph import build_graph
from tchekam.ai.agent.models import fake_model
from tchekam.ai.agent.policy import authorize, consume
from tchekam.ai.agent.schemas import AgentDenied, ModelUnavailable
from tchekam.ai.agent.tasks import deliver, reconcile
from tchekam.ai.agent.tools import execute
from tchekam.ai.models import AgentBudget, AgentControl, AgentDelivery, AgentRun
from tchekam.conversations.models import Conversation
from tchekam.i18n import t
from tchekam.imaging.models import Image as StoredImage
from tchekam.imaging.models import ImageSighting

pytestmark = pytest.mark.django_db(transaction=True)


def test_competing_workers_cannot_spend_last_allowance_twice(make_run):
    ctx = claim(make_run().pk)
    ready = Barrier(2)

    def attempt(call_id):
        ready.wait(timeout=5)
        try:
            reserve(ctx, call_id, 60)
            return "reserved"
        except AgentDenied:
            return "denied"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["worker-one", "worker-two"]))
    assert sorted(results) == ["denied", "reserved"]
    assert set(AgentBudget.objects.values_list("used", flat=True)) == {60}


def test_recovery_fences_late_worker_and_preserves_counts(make_run):
    run = make_run()
    previous = claim(run.pk)
    consume(previous, "model_calls")
    AgentRun.objects.filter(pk=run.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    with patch("tchekam.ai.agent.tasks.enqueue"):
        reconcile()
    with pytest.raises(AgentDenied):
        authorize(previous)
    current = claim(run.pk)
    assert current.fence > previous.fence
    assert current.model_calls == 1


def test_processing_deadline_returns_reviewed_fallback(make_run, fake_channel):
    run = make_run()
    ctx = claim(run.pk)
    ctx.model = fake_model()
    ctx.deadline = monotonic() - 1
    state = build_graph(ctx).invoke({"run_id": run.pk})
    assert state["completed"] and ctx.model_calls == 0
    assert state["replies"] == [t("common.coming_soon", "en")]


def test_kill_switch_cancels_pending_delivery_even_after_reenable(make_run, fake_channel):
    run = make_run()
    AgentRun.objects.filter(pk=run.pk).update(status="complete", completed_at=timezone.now())
    row = AgentDelivery.objects.create(run=run, index=0, generation=0, text="synthetic")
    control = AgentControl.objects.get(pk=1)
    control.enabled = False
    control.save()
    control.enabled = True
    control.save()
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "cancelled" and fake_channel.sent == []


def test_block_unblock_invalidates_old_generation(make_run, actor):
    run = make_run()
    ctx = claim(run.pk)
    actor.blocked = True
    actor.save()
    actor.blocked = False
    actor.save()
    with pytest.raises(AgentDenied):
        authorize(ctx)
    assert Conversation.objects.get(user=actor).agent_generation > run.generation


def test_private_photo_lookup_never_uploads_or_adopts_media(make_run, fake_channel):
    run = make_run("Is this photo reused?", kind="image")
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(image, "PNG")
    fake_channel.media[run.inbound_key] = (image.getvalue(), "image/png")
    ctx = claim(run.pk)
    handle = execute(ctx, "check_photo", {"media_ref": "current_image"})
    assert t("check.photo.no_match", "en") in ctx.results[handle].texts[0]
    assert not StoredImage.objects.exists() and not ImageSighting.objects.exists()
    assert fake_channel.downloads == [run.inbound_key]
    with pytest.raises(AgentDenied, match="media_replay"):
        execute(ctx, "check_photo", {"media_ref": "current_image"})


def test_disabled_vision_does_not_download_private_image(make_run, fake_channel):
    ctx = claim(make_run("Read this screenshot", kind="image").pk)
    with pytest.raises(ModelUnavailable):
        execute(ctx, "read_image", {"media_ref": "current_image", "task": "phone_numbers"})
    assert fake_channel.downloads == []


def test_masked_name_lookup_cannot_expose_input_name(make_run):
    ctx = claim(make_run().pk)
    handle = execute(ctx, "check_account_name", {"name": "JEAN PAUL", "operator": "momo"})
    text = ctx.results[handle].texts[0]
    assert "JEAN PAUL" not in text and "J*** P***" in text
