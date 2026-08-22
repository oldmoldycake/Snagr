"""Suggestion and auto-promotion guardrails (D-V7).

Suggestions put an image in the owner's review queue with a pre-picked
label; auto-promotion turns one straight into a gold reference, and is the
feature's self-training drift vector (risk 3) — hence every guardrail here
must pass independently. Auto-promotion is evaluated at capture time only;
a rescore re-runs suggestions but never promotion (D-V8 boundary).
"""

from scoring import ImageScore

# An image enters the review queue when its confidence clears this.
SUGGEST_THRESHOLD = 0.80
# Real suggestions additionally need a strong absolute match — weak
# reassurance must not grow the real cluster (D-V5 asymmetry).
REAL_SUGGEST_MIN_SIMILARITY = 0.80
# Guardrail 1: the item needs this many human-vouched (human/upload) refs of
# the label before anything self-promotes — the earliest, most error-prone
# judgments can never compound.
MIN_GOLD_FOR_AUTO = 3


def suggest_label(score: ImageScore) -> str | None:
    """The label to queue this image under, or None to stay out of the queue."""
    if score.fake_confidence is None:
        return None
    if score.fake_confidence >= SUGGEST_THRESHOLD:
        return "fake"
    if (
        score.fake_confidence <= 1 - SUGGEST_THRESHOLD
        and score.real_similarity is not None
        and score.real_similarity >= REAL_SUGGEST_MIN_SIMILARITY
    ):
        return "real"
    return None


def corroborates(label: str, llm_authenticity_read: str | None) -> bool:
    """Guardrail 3: the LLM's independent read at scan time must agree —
    fake ↔ suspect, real ↔ looks_authentic; unsure never corroborates."""
    return (label == "fake" and llm_authenticity_read == "suspect") or (
        label == "real" and llm_authenticity_read == "looks_authentic"
    )


def auto_promotable(
    label: str,
    score: ImageScore,
    llm_authenticity_read: str | None,
    vouched_gold_count: int,
    auto_promote_real: float,
    auto_promote_fake: float,
) -> bool:
    """Whether a suggested image may become a gold reference unattended.

    vouched_gold_count counts the item's live human/upload references of
    `label` — provenance 'auto' rows never count, so promotions can't
    bootstrap further promotions.
    """
    if vouched_gold_count < MIN_GOLD_FOR_AUTO:
        return False
    if score.fake_confidence is None:
        return False
    if label == "fake":
        confidence, threshold = score.fake_confidence, auto_promote_fake
    else:
        confidence, threshold = 1 - score.fake_confidence, auto_promote_real
    if confidence < threshold:
        return False
    return corroborates(label, llm_authenticity_read)
