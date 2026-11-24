import pytest
from procrastinate.contrib.django.models import ProcrastinateJob

from tchekam.core import tasks

CALLS = []


@tasks.register("tests.record")
def record(value):
    CALLS.append(value)


@pytest.fixture(autouse=True)
def _clear_calls():
    CALLS.clear()


def test_enqueue_runs_inline_when_eager():
    tasks.enqueue("tests.record", value=1)

    assert CALLS == [1]


def test_unknown_task_raises():
    with pytest.raises(tasks.UnknownTaskError):
        tasks.enqueue("tests.nope")


@pytest.mark.django_db
def test_enqueue_defers_to_procrastinate_when_not_eager(settings):
    settings.TASKS_EAGER = False

    tasks.enqueue("tests.record", value=2, queue="slow", schedule_in_seconds=60)

    job = ProcrastinateJob.objects.get(task_name="tests.record")
    assert job.args == {"value": 2}
    assert job.queue_name == "slow"
    assert job.scheduled_at is not None
    assert CALLS == []


@pytest.mark.django_db
def test_enqueue_passes_the_lock_to_procrastinate(settings):
    settings.TASKS_EAGER = False

    tasks.enqueue("tests.record", value=3, queue="whatsapp", lock="whatsapp-1")

    job = ProcrastinateJob.objects.get(task_name="tests.record", args={"value": 3})
    assert job.lock == "whatsapp-1"
    assert job.lock_mode == "mutex"


def test_cron_registers_a_periodic_task():
    from procrastinate.contrib.django import app

    @tasks.register("tests.periodic", cron="0 * * * *")
    def periodic(timestamp):
        pass

    assert any(
        p.task.name == "tests.periodic" for p in app.periodic_registry.periodic_tasks.values()
    )


def test_eager_rejects_non_json_args():
    with pytest.raises(TypeError):
        tasks.enqueue("tests.record", value=object())


def test_duplicate_registration_raises():
    with pytest.raises(ValueError):
        tasks.register("tests.record")(lambda value: None)
