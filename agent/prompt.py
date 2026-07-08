"""Prompt construction for the shopping-research agent: one prompt per
(watch, site) pair, with blocks that vary by selection mode and whether
reproductions are allowed."""


async def generate_prompt(
    watch_id: str,
    site_id: str,
    site_name: str,
    item_id: str,
    item_name: str,
    base_url: str,
    criteria: str|None,
    selection_mode: str,
    max_listings: int,
    allow_reproductions: bool,
    known_urls: list[str] | None = None,
    rejected_checks: list | None = None,
) -> str:
    """
    Build the instruction prompt for the LLM agent for ONE (watch, site) pair.

    args:
        watch_id:             Internal ID of the watch (user+item) this run is for.
        site_id:              Internal ID of the site being searched.
        site_name:            Human-readable name of the site being searched.
        item_id:              Internal ID of the item being searched for.
        item_name:            Human-readable name of the item being searched for.
        base_url:             The site's base URL — where the agent starts browsing.
        criteria:             This watch's matching criteria (best_match only).
        selection_mode:       "best_match" or "cheapest" for this watch.
        max_listings:         How many listings to save for this watch (1-10).
        allow_reproductions:  Whether this watch's user has explicitly said
                              reproductions/replicas are acceptable for this item.
        known_urls:           URLs already tracked/checked — the agent should
                              skip these rather than re-evaluate them.
        rejected_checks:      Rows from get_checked_urls (with "url", "reason",
                              and optionally "notes" keys) for listings on this
                              site already evaluated and rejected for this watch.

    return:
        str: The prompt for the LLM agent.
    """

    if not criteria:
        criteria = f"Any genuine, reasonably-priced listing for: {item_name}."
    # target_price is a notify threshold only; it does NOT need to be met to save a listing.

    # --- Selection/ranking block: branches on selection_mode. -----------------
    if selection_mode == "best_match":
        selection_block = (
            f"SELECTION MODE: best_match.\n"
            f"The user is looking for: \"{criteria}\".\n"
            f"Do NOT stop searching and saving as soon as you find one acceptable listing. "
            f"Search the site thoroughly first and build a mental pool of every reasonable "
            f"candidate you find, then judge each candidate against the criteria and rank "
            f"them by how well they fit (best fit first); use price as a tiebreaker when two "
            f"candidates fit equally well. Your target is to save exactly {max_listings} "
            f"listing(s) — keep searching until you have that many genuinely reasonable "
            f"candidates or you have exhausted what the site has to offer. Only save fewer "
            f"than {max_listings} if the site genuinely does not have that many reasonable "
            f"matches; do not pad the count with poor fits just to hit the target, but do not "
            f"settle for a single result when more good candidates are available either. "
            f"Do not save any candidate whose match_score would be below 50 — leave the "
            f"slot empty instead of tracking a poor match."
        )
    else:  # "cheapest" (the real default)
        selection_block = (
            f"SELECTION MODE: cheapest.\n"
            f"Rank the candidate listings by price, lowest first, and keep the "
            f"{max_listings} cheapest listing(s) that are genuinely the item described. "
            f"Ignore the criteria for ranking; price is the only ranking signal."
        )

    # --- Authenticity block: skipped entirely if the user opted in. ----------
    if allow_reproductions:
        authenticity_block = (
            "AUTHENTICITY: the user has explicitly allowed "
            "reproductions/replicas/counterfeits for this item, so skip "
            "authenticity screening entirely — judge listings purely on the "
            "criteria above."
        )
    else:
        authenticity_block = f"""AUTHENTICITY IS A HARD GATE (checked before ranking/scoring)
  Counterfeits, reproductions, replicas, and unauthorized clones exist for
  many kinds of collectible/resale items, not just one product category —
  "{item_name}" may or may not be a common counterfeit target, so actively
  screen for it rather than assuming it's fine. Before considering a listing
  as a candidate at all, screen it for red flags such as:
    - Title/description uses words like "repro", "reproduction", "replica",
      "custom", "fan made", "not authentic", "inspired by", "AAA quality"
      (common counterfeit-marketplace euphemism), or similar hedging language.
    - Seller has many near-identical listings for the same item (a hallmark
      of counterfeit/repro sellers), or the listing otherwise reads like a
      mass-produced knockoff rather than a single used/original item.
    - Price is far below the going rate for a genuine item in the stated
      condition.
    - Description mentions non-original components, modifications, or
      unbranded/generic packaging where an original would have official
      packaging or markings.
  If a listing shows ANY of these signs, do NOT save it — note it as
  rejected-for-authenticity and move on, regardless of how well it otherwise
  fits price or condition criteria. Authenticity concerns override price and
  condition fit; do not let a good price talk you into a lower authenticity bar.
  If you are uncertain whether a listing is authentic after checking the page,
  treat that uncertainty as a reason to lower the match_score sharply, not ignore it."""

    if known_urls:
        known_urls_list = "\n".join(f"    - {u}" for u in known_urls)
        known_urls_block = f"""ALREADY-TRACKED URLS — SKIP THESE
  The following URLs are already tracked/checked; do NOT save them again or
  spend time re-evaluating them as new candidates:
{known_urls_list}
"""
    else:
        known_urls_block = ""

    if rejected_checks:
        rejected_list = "\n".join(
            f"    - {c['url']} (rejected: {c['reason']}"
            + (f" — {c['notes']}" if c.get("notes") else "")
            + ")"
            for c in rejected_checks
        )
        rejected_checks_block = f"""PREVIOUSLY REJECTED LISTINGS — DO NOT RECONSIDER
  You already evaluated the following listings on this site for this watch
  and rejected them. Skip them entirely unless the URL now points to an
  obviously different listing (e.g. the site reused the URL for a new item):
{rejected_list}
"""
    else:
        rejected_checks_block = ""

    prompt = f"""You are an autonomous shopping-research agent. You have a real web browser
available through the Playwright tools (navigate, snapshot, click, type, etc.).

YOUR TASK
Search exactly ONE site for a specific product and record the matching listings.

  - Site:      {site_name} (site_id={site_id})
  - Start URL: {base_url}
  - Item:      {item_name} (item_id={item_id})

RULES
  - Stay on {site_name} only. Start at the Start URL above and use the site's own
    search/navigation to find the product. Do NOT browse to other websites.
  - Work only from what you actually see on the page. NEVER invent products,
    URLs, prices, SKUs, or stock status. If you cannot find anything, save nothing.
  - Search via the site's UI, not hand-built URLs: load the site's homepage,
    type the query into its search box, and submit. Many sites (eBay especially)
    block directly-constructed search URLs with a 403/error page while the same
    search works fine through the search box. If a page comes back as an error
    page or looks blocked, do not keep retrying URL variants of the same idea —
    switch to the search-box approach, and if the site still blocks you after a
    few genuinely different attempts, stop and report that the site was
    inaccessible rather than looping.

{known_urls_block}
{rejected_checks_block}
{authenticity_block}

{selection_block}

FOR EACH LISTING YOU DECIDE TO SAVE
  1. Call `save_listing` with:
       - watch_id={watch_id}, item_id={item_id}, site_id={site_id}
       - url:           the product page URL you actually visited
       - title:         the listing's actual title, exactly as shown on the site
       - site_sku:      the site's SKU if one is shown, otherwise omit it
       - match_score:   an integer 0–100 for how well this listing is the item
                        described and (in best_match mode) fits the criteria.
                        Be calibrated — do not default to high.
       - match_summary: ONE short line justifying that score: what matched,
                        what didn't, and note that you checked for
                        reproduction/counterfeit red flags and found none (or
                        which authenticity signals gave you pause).
                        Example: "dry battery ✓, damaged case ✓, cart only, no repro flags"
     `save_listing` returns a `listing_id` (int) on success, or an error string.
  2. If you got a numeric `listing_id`, immediately call `save_price_check` with:
       - listing_id: the EXACT id returned by that save_listing call. NEVER
                     guess, infer, or reuse a listing_id you did not just
                     receive — a wrong id silently attaches this price to a
                     different listing, which is data corruption.
       - price:      the numeric price shown (no currency symbol)
       - currency:   the currency shown, e.g. "USD"
       - in_stock:   true/false based on the page
       - status:     exactly one of "ok", "sold", "ended", "error". Use "ok"
                     for a live listing (whether or not it is in stock);
                     "sold"/"ended" only when the listing has terminally
                     concluded.
     Call `save_price_check` exactly ONCE per listing. If status was "sold" or
     "ended", immediately follow it with `disable_listing` (same listing_id)
     so it stops being tracked. Once done, that listing is finished — do not
     call `save_price_check` again for it this run.
     If `save_listing` returned an error string instead of an id, do NOT call
     `save_price_check` for it — note the error and move on.
  3. If `save_listing` errors, call it AT MOST once more for that same listing,
     with the exact same real data — never with placeholder/dummy values like
     "Test" or a fabricated URL to "debug" the tool. These tools write directly
     to a production database; every call must describe a real listing you
     found on the page. If it errors twice, log the error and move on to the
     next candidate — do not keep retrying the same listing.

FOR EACH CANDIDATE YOU EVALUATE BUT DO NOT SAVE
  Call `log_listing_check` with watch_id={watch_id}, site_id={site_id}, the
  listing's url, a short reason ("poor_fit", "duplicate", "authenticity",
  etc.), and optional notes. This applies to genuine candidates you looked at
  and rejected — not to search-result pages or listings you never opened.

WHEN DONE
  Stop once you have saved the selected listings (up to {max_listings}), or once
  you are confident the site has no reasonable match. Do not loop endlessly.
"""

    return prompt


async def generate_recheck_prompt(
    listing_id: int,
    listing_url: str,
    watch_id: str,
    site_id: str,
    site_name: str,
    item_id: str,
    item_name: str,
) -> str:
    """
    Build the instruction prompt for the LLM agent to re-check ONE already-
    tracked listing: revisit its URL and record its current price/availability.

    args:
        listing_id:   Internal ID of the existing listing being re-checked.
        listing_url:  The listing's saved product page URL to revisit.
        watch_id:     Internal ID of the watch (user+item) this listing belongs to.
        site_id:      Internal ID of the site the listing is on.
        site_name:    Human-readable name of the site the listing is on.
        item_id:      Internal ID of the item this listing is for.
        item_name:    Human-readable name of the item this listing is for.

    return:
        str: The prompt for the LLM agent.
    """

    prompt = f"""You are an autonomous shopping-research agent. You have a real web browser
available through the Playwright tools (navigate, snapshot, click, type, etc.).

YOUR TASK
Re-check ONE listing you are already tracking and record its current price
and availability. You are NOT searching for new listings this run.

  - Site:         {site_name} (site_id={site_id})
  - Listing URL:  {listing_url}
  - Item:         {item_name} (item_id={item_id})
  - listing_id:   {listing_id}

RULES
  - Navigate directly to the Listing URL above. Do NOT search the site or
    browse anywhere else.
  - Work only from what you actually see on the page. NEVER invent a price,
    stock status, or outcome.
  - A page that 404s, redirects to a search/homepage, or otherwise no longer
    resolves to the original item means the listing is gone: treat that as
    status="ended".
  - A page that explicitly shows the item as sold/no-longer-available means
    status="sold".
  - A page that loads, still shows the same item for sale, AND has a visible
    price means status="ok" (regardless of whether it happens to be in or out
    of stock right now — use in_stock for that).
  - A page that loads and still resolves to the same item but you cannot find
    a price anywhere on it is NOT status="ok" — that is ambiguous/broken, not
    confirmed-live. Use status="error" in that case rather than guessing.
  - If the page fails to load for a transient reason (timeout, error page
    unrelated to the listing itself), retry navigation once; if it still
    fails, use status="error".

WHEN DONE
  Call `save_price_check` exactly ONCE with:
    - listing_id: {listing_id} — use this exact id, never a different one.
    - price:      the numeric price currently shown (no currency symbol).
                  OMIT this argument entirely if status is "sold", "ended",
                  or "error" — never send 0 or any other placeholder number
                  as the price. status="ok" REQUIRES a real, visible price;
                  if you have no price, you cannot use status="ok".
    - currency:   the currency shown, e.g. "USD"
    - in_stock:   true/false based on the page
    - status:     exactly one of "ok", "sold", "ended", "error" per the RULES above.
  Call `save_price_check` at most twice for this listing (once, plus one retry
  if the first call errors) — never with placeholder/dummy values.

  If status was "sold" or "ended", immediately follow up with `disable_listing`
  using listing_id={listing_id} so it stops being tracked. Do not call
  `disable_listing` for status "ok" or "error". Then stop.
"""

    return prompt
