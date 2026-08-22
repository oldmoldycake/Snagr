"""Table-tests for the D-V10 formula — pure math, no DB, no app.

Geometry convention (see conftest.vec): gold-real refs at 0°, gold-fake refs
at 90°, candidates in between; cosine(vec(a), vec(b)) == cos(a−b).
"""

import pytest
from scoring import ImageScore, rollup, score_image

from tests.conftest import off_plane, vec

REAL = [vec(0)]
FAKE = [vec(90)]


def test_no_references_is_inconclusive():
    score = score_image(vec(20), [], [])
    assert score.verdict == "inconclusive"
    assert score.fake_confidence is None
    assert score.real_similarity is None
    assert score.fake_similarity is None


def test_far_from_everything_fails_safe():
    # an unseen variant / novel angle matches nothing — below the absolute
    # floor no margin may be read as evidence (risk 1)
    score = score_image(off_plane(), REAL, FAKE)
    assert score.verdict == "inconclusive"
    assert score.fake_confidence is None
    assert score.real_similarity == pytest.approx(0.0, abs=1e-6)


def test_margin_maps_to_confidence():
    # equidistant → dead-center confidence, inconclusive
    mid = score_image(vec(45), REAL, FAKE)
    assert mid.fake_confidence == pytest.approx(0.5, abs=1e-3)
    assert mid.verdict == "inconclusive"

    # clearly closer to real → confidence clamps to 0
    real_side = score_image(vec(30), REAL, FAKE)
    assert real_side.fake_confidence == pytest.approx(0.0, abs=1e-3)
    assert real_side.verdict == "leans_real"

    # clearly closer to fake → confidence clamps to 1
    fake_side = score_image(vec(60), REAL, FAKE)
    assert fake_side.fake_confidence == pytest.approx(1.0, abs=1e-3)
    assert fake_side.verdict == "leans_fake"


def test_fake_only_library_condemns():
    # the floor substitutes for the missing real side, so even a modest fake
    # match condemns — the evidence-asymmetry lever (D-V5)
    strong = score_image(vec(80), [], FAKE)
    assert strong.verdict == "leans_fake"
    assert strong.fake_confidence == pytest.approx(1.0, abs=1e-3)

    modest = score_image(vec(36.9), [], FAKE)  # s_fake ≈ 0.60
    assert modest.verdict == "leans_fake"
    assert modest.fake_confidence == pytest.approx(0.667, abs=1e-2)


def test_real_only_library():
    # dissimilarity to known reals is NOT evidence of fakeness
    distant = score_image(vec(80), REAL, [])
    assert distant.verdict == "inconclusive"
    assert distant.fake_confidence is None

    # a strong real match yields leans_real — weak reassurance, but a verdict
    close = score_image(vec(10), REAL, [])
    assert close.verdict == "leans_real"
    assert close.fake_confidence == pytest.approx(0.0, abs=1e-3)


def _score(verdict: str, fake_confidence: float | None) -> ImageScore:
    return ImageScore(None, None, fake_confidence, verdict)


def test_rollup_one_fake_photo_condemns_the_listing():
    verdict, confidence = rollup(
        [_score("leans_real", 0.05), _score("leans_fake", 0.9), _score("leans_real", 0.1)]
    )
    assert verdict == "leans_fake"
    assert confidence == 0.9  # the worst image speaks for the listing


def test_rollup_leans_real_needs_every_scored_image():
    verdict, _ = rollup([_score("leans_real", 0.1), _score("inconclusive", 0.5)])
    assert verdict == "inconclusive"

    verdict, confidence = rollup([_score("leans_real", 0.1), _score("leans_real", 0.2)])
    assert verdict == "leans_real"
    assert confidence == 0.2


def test_rollup_unscored_images_do_not_block():
    # a floor-failed photo is evidence of nothing either way
    verdict, confidence = rollup([_score("leans_real", 0.1), _score("inconclusive", None)])
    assert verdict == "leans_real"
    assert confidence == 0.1


def test_rollup_nothing_scored_is_inconclusive():
    assert rollup([]) == ("inconclusive", None)
    assert rollup([_score("inconclusive", None)]) == ("inconclusive", None)
