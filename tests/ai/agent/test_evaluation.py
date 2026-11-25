import io

import pytest
from evals.agent.run import nearest_rank_p95, validate_cases
from evals.agent.vision_fixtures import cases, render
from PIL import Image


@pytest.mark.parametrize(
    "cases",
    [
        [],
        [{"id": "x", "lang": "fr", "input": "hello"}] * 2,
        [{"id": "x", "lang": "unknown", "input": "hello"}],
        [{"id": "x", "lang": "fr", "input": " "}],
    ],
)
def test_invalid_datasets_are_rejected(cases):
    with pytest.raises(ValueError):
        validate_cases(cases)


def test_p95_includes_tail_in_small_media_collections():
    assert nearest_rank_p95([3, 1, 2]) == 3
    assert nearest_rank_p95(range(1, 25)) == 23
    with pytest.raises(ValueError):
        nearest_rank_p95([])


def test_screenshot_fixtures_are_bounded_synthetic_pngs():
    fixtures = cases()
    assert len(fixtures) == 3
    assert {case["lang"] for case in fixtures} == {"fr", "en", "pcm"}
    for case in fixtures:
        data = render(case["lang"], injection=case["id"].endswith("injection"))
        image = Image.open(io.BytesIO(data))
        assert image.format == "PNG" and image.size == (1200, 760)
        assert len(data) < 1_000_000
        assert case["tool"] == "read_image"
