"""max_listings is one slot budget per watch across every site and run, not
a per-site quota. The discovery prompt spells that out and addresses the
model in open slots (the cap minus what the watch already holds), so a watch
with three sites no longer fills 3x its cap and every run no longer adds
another round on top."""

import asyncio

from prompt import generate_prompt


def _prompt(**overrides) -> str:
    args = {
        "watch_id": 1,
        "site_id": 2,
        "site_name": "TestBay",
        "item_id": 3,
        "item_name": "Widget",
        "base_url": "https://example.test",
        "criteria": None,
        "selection_mode": "cheapest",
        "max_listings": 5,
        "allow_reproductions": False,
        **overrides,
    }
    return asyncio.run(generate_prompt(**args))


def test_the_budget_is_stated_as_a_watch_wide_cap():
    prompt = _prompt(tracked_listings=3)
    assert "TRACKING SLOTS: 2 open" in prompt
    assert "at most 5 listing(s) IN TOTAL" in prompt
    assert "not 5 per site" in prompt
    assert "3 slot(s) are already filled" in prompt
    assert "Save at most 2 new listing(s) this run" in prompt


def test_selection_and_stop_rules_count_open_slots_not_the_cap():
    cheapest = _prompt(tracked_listings=3)
    assert "keep the 2 cheapest listing(s)" in cheapest
    assert "keep the 5 cheapest" not in cheapest
    assert "(up to 2)" in cheapest
    assert "(up to 5)" not in cheapest

    best_match = _prompt(tracked_listings=3, selection_mode="best_match", criteria="boxed")
    assert "save exactly 2 listing(s)" in best_match
    assert "Only save fewer than 2" in best_match
    assert "exactly 5" not in best_match


def test_an_untouched_watch_has_every_slot_open():
    # the default: callers that pass no count get the cap itself
    prompt = _prompt()
    assert "TRACKING SLOTS: 5 open" in prompt
    assert "0 slot(s) are already filled" in prompt
    assert "keep the 5 cheapest listing(s)" in prompt


def test_an_over_full_watch_clamps_to_zero_open():
    # watches over-filled before the cap was enforced must not go negative
    prompt = _prompt(tracked_listings=39)
    assert "TRACKING SLOTS: 0 open" in prompt
    assert "-34" not in prompt


def test_leftover_candidates_are_not_logged_as_rejections():
    # logging them would land them in PREVIOUSLY REJECTED and hide them from
    # the run that finally has a free slot
    prompt = _prompt(tracked_listings=3)
    assert "Leftover good candidates are NOT rejections" in prompt
    assert "do not log them with `log_listing_check`" in prompt
