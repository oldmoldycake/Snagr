"""ALL verdict math for the visual-authenticity check (D-V10) — pure
functions over vectors and labels, nothing else in the project computes a
score. Deliberately independent of how neighbors are fetched, so swapping
the sequential scan for an ANN index later never touches the formula.

The formula fails toward `inconclusive` on purpose (risk 1: photo conditions
dominate global embeddings), and encodes the D-V5 evidence asymmetry:
matching known fakes condemns strongly, matching known reals only weakly
reassures — scammers post stock photos of genuine items.
"""

from dataclasses import dataclass

import numpy as np

# Below this cosine similarity a match means nothing: "far from everything"
# (unseen variant, novel angle) maps to inconclusive, never to a side.
ABS_FLOOR = 0.55
# Margin → confidence steepness: a real/fake gap of MARGIN_SCALE reaches full
# confidence on that side; smaller gaps land proportionally near 0.5.
MARGIN_SCALE = 0.15
# fake_confidence bounds for a per-image verdict; the band between them is
# inconclusive.
LEANS_FAKE_AT = 0.65
LEANS_REAL_AT = 0.35


@dataclass
class ImageScore:
    """One image scored against an item's live gold library."""

    real_similarity: float | None  # nearest gold-real cosine; None = no real refs
    fake_similarity: float | None  # nearest gold-fake cosine; None = no fake refs
    fake_confidence: float | None  # None = the library couldn't score this image
    verdict: str  # leans_real | leans_fake | inconclusive


def cosine(a, b) -> float:
    """Cosine similarity between two vectors (any array-likes)."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _nearest(embedding, references: list) -> float | None:
    if not references:
        return None
    return max(cosine(embedding, ref) for ref in references)


def score_image(embedding, real_refs: list, fake_refs: list) -> ImageScore:
    """Score one embedding against the live gold references of each label.

    Variant-tagged reals are passed in with the rest of real_refs — variants
    are sub-clusters under real (D-V5), not a separate label.
    """
    s_real = _nearest(embedding, real_refs)
    s_fake = _nearest(embedding, fake_refs)

    defined = [s for s in (s_real, s_fake) if s is not None]
    if not defined or max(defined) < ABS_FLOOR:
        return ImageScore(s_real, s_fake, None, "inconclusive")

    # A missing side substitutes the floor, not 0 — the asymmetry lever: a
    # strong fake match with zero real refs still condemns, a strong real
    # match with zero fake refs merely reassures.
    margin = (s_fake if s_fake is not None else ABS_FLOOR) - (
        s_real if s_real is not None else ABS_FLOOR
    )
    fake_confidence = min(max(0.5 + margin / (2 * MARGIN_SCALE), 0.0), 1.0)

    if fake_confidence >= LEANS_FAKE_AT:
        verdict = "leans_fake"
    elif fake_confidence <= LEANS_REAL_AT and s_real is not None and s_real >= ABS_FLOOR:
        verdict = "leans_real"
    else:
        verdict = "inconclusive"
    return ImageScore(s_real, s_fake, fake_confidence, verdict)


def rollup(scores: list[ImageScore]) -> tuple[str, float | None]:
    """Listing-level verdict from per-image scores — asymmetric on purpose:
    one faked photo condemns the listing; leans_real needs EVERY scored
    image to lean real. Returns (verdict, fake_confidence), the confidence
    being the worst (max) over scored images."""
    scored = [s for s in scores if s.fake_confidence is not None]
    fake_confidence = max(s.fake_confidence for s in scored) if scored else None

    if any(s.verdict == "leans_fake" for s in scored):
        return "leans_fake", fake_confidence
    if scored and all(s.verdict == "leans_real" for s in scored):
        return "leans_real", fake_confidence
    return "inconclusive", fake_confidence
