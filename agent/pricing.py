import asyncio
import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median
from urllib.parse import urlparse

import requests
from config import (
    AI_API_KEY,
    AI_MODEL,
    AI_PROVIDER,
    AI_URL,
    EXPECTED_CURRENCY,
    MARKET_PRICE_MAX_REFRESH_PER_RUN,
    MARKET_PRICE_TTL_HOURS,
    SEARXNG_URL,
)
from database import (
    get_category_item_names,
    get_category_tiers,
    get_grounding_candidates,
    get_item_grounding,
    get_price_sources,
    set_condition_tiers,
    set_guide_pages,
    set_price_sources,
    upsert_market_price,
)
from langchain.chat_models import init_chat_model
from prompt import generate_condition_tiers_prompt, generate_price_extraction_prompt

if AI_API_KEY:
    llm = init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL, api_key=AI_API_KEY)
else:
    llm = init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL)

log = logging.getLogger(__name__)

# Two query shapes on purpose: question-style surfaces forums and wikis,
# sold/guide-style surfaces marketplaces and price guides, with little overlap.
QUERY_TEMPLATES = [
    "What is a {} worth",
    "How much does {} sell for",
    "{} estimated value",
    "{} sold price",
    "{} ebay sold",
    "{} price guide",
    "{} loose cib sealed price",
]

# Pages per query; this SearXNG instance returns nothing past page 5.
SEARCH_PAGES = 3

# SearXNG suspends its upstream engines when queried too fast. Grounding is not
# time-sensitive, so pace generously and back off long when it happens anyway.
INTER_REQUEST_DELAY_S = 5.0
SUSPENSION_BACKOFF_S = 900

# Snippets priced only in some other currency never reach extraction.
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
PRICE_TOKEN = re.compile(
    rf"{re.escape(CURRENCY_SYMBOLS.get(EXPECTED_CURRENCY, '$'))}\s?\d[\d,]*(?:\.\d{{2}})?"
)
SNIPPET_YEAR = re.compile(r"\b20\d{2}\b")
# Older quotes describe a collectibles market that no longer exists.
MAX_SNIPPET_AGE_YEARS = 2

# Coarse fallback when a category has no stored tiers and generation fails.
DEFAULT_CONDITION_TIERS = ["new", "used"]

SOURCE_TYPES = {"price_guide", "marketplace", "retailer", "social", "other"}

# Price-guide pages are static server-rendered HTML (being indexed is their
# business), so fetching them whole needs only a plain GET, no browser.
GUIDE_PAGE_MAX_CHARS = 8000
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Registry lifecycle: trust comes from evidence, never from the LLM's word.
# A fetch that parses into PROMOTE_MIN_TIERED_OBS tier-tagged observations is
# a hit and promotes a candidate; anything less is a miss. Candidates that
# never hit die fast; even a trusted domain dies after enough consecutive
# misses. Pinned domains are user-owned and exempt from all of it.
PROMOTE_MIN_TIERED_OBS = 2
CANDIDATE_DEAD_MISSES = 3
DEAD_CONSECUTIVE_MISSES = 5
# Below this many productive domains, ONE candidate gets probed this run -
# candidates earn promotion without burning the whole search budget.
MIN_PRODUCTIVE_DOMAINS = 2
SOURCE_FETCH_TIMEOUT_S = 15

# Below this a tier is stored but not reported: two prices from one eBay page
# once published "loose $137" while the real loose market sat around $226.
MIN_TIER_SAMPLE = 3

# How far above its own tier's median a price has to sit before it reads as a
# transcription error rather than an expensive copy. Deliberately loose: graded
# copies span an order of magnitude by grade, and a tier that wide is normal.
OUTLIER_RATIO = 20


async def search_searxng(
    queries: list[str], base_url: str = "http://localhost:8888", pages: int = SEARCH_PAGES
) -> dict[str, str] | None:
    """Run each query against SearXNG and merge the results into
    {url: snippet}, deduped by url across queries and pages."""
    try:
        search_results = {}
        backed_off = False

        for query in queries:
            pageno = 1
            while pageno <= pages:
                log.info(f"Searching SearXNG (page {pageno}): {query}")
                params = {"q": query, "format": "json", "pageno": pageno}
                response = requests.get(f"{base_url}/search", params=params, timeout=10)
                response.raise_for_status()
                response_json = response.json()

                results = response_json["results"]

                # A suspension looks like success - HTTP 200 with an empty
                # result list - so raise_for_status never sees it. Suspensions
                # expire on their own; sleep it off and retry once.
                if not results:
                    suspended = response_json.get("unresponsive_engines") or []
                    if suspended and not backed_off:
                        backed_off = True
                        log.warning(
                            f"SearXNG engines suspended ({suspended}), "
                            f"backing off {SUSPENSION_BACKOFF_S}s before one retry"
                        )
                        await asyncio.sleep(SUSPENSION_BACKOFF_S)
                        continue
                    if suspended:
                        log.error(f"SearXNG engines still suspended, stopping search: {suspended}")
                        return search_results
                    log.warning(f"No results on page {pageno} for: {query}")
                    break

                known = len(search_results)
                for result in results:
                    # Not every engine returns a snippet; the url is what dedupes.
                    search_results[result["url"]] = result.get("content") or ""
                log.info(
                    f"{len(results)} results, {len(search_results) - known} new "
                    f"({len(results) - (len(search_results) - known)} already seen)"
                )

                pageno += 1
                await asyncio.sleep(INTER_REQUEST_DELAY_S)

        log.info(f"SearXNG search completed: {len(search_results)} unique urls")
        return search_results

    except Exception as e:
        log.error(f"Error searching SearXNG: {e}")


async def search_searxng_queries(
    item: str, base_url: str = "http://localhost:8888"
) -> dict[str, str] | None:
    """Run every query template for one item - the broad-market snippet search
    the fallback ladder escalates to when guides come up dry."""
    return await search_searxng([template.format(item) for template in QUERY_TEMPLATES], base_url)


def site_query(domain: str, alias: str) -> str:
    """One site-scoped query: how a guide page is found the first time. A
    handful of these per item stays under SearXNG's suspension threshold in a
    way the broad template shotgun does not."""
    return f"site:{domain} {alias}"


def pick_domain_url(search_results: dict[str, str], domain: str) -> str | None:
    """First result actually hosted on the queried domain. site: queries can
    leak other hosts, and fetching those would credit or blame the wrong
    registry entry. Subdomains belong to the domain; lookalike hosts that
    merely end in its name do not."""
    wanted = domain.removeprefix("www.").lower()
    for url in search_results:
        host = (urlparse(url).hostname or "").removeprefix("www.").lower()
        if host == wanted or host.endswith("." + wanted):
            return url
    return None


def filter_snippets(search_results: dict[str, str]) -> dict[str, str]:
    """Drop snippets that cannot produce a usable price, before they cost any
    extraction tokens: ones with no price anywhere in the text, and ones whose
    newest date is older than MAX_SNIPPET_AGE_YEARS. Undated snippets are kept
    on purpose - price guides are evergreen and rarely carry a date, and they
    are the sources worth having."""
    cutoff = datetime.now().year - MAX_SNIPPET_AGE_YEARS
    kept = {}
    no_price = 0
    stale = 0

    for url, snippet in search_results.items():
        if not PRICE_TOKEN.search(snippet):
            no_price += 1
            continue

        years = [int(year) for year in SNIPPET_YEAR.findall(snippet)]
        if years and max(years) < cutoff:
            stale += 1
            continue

        kept[url] = snippet

    log.info(
        f"Snippet filter kept {len(kept)}/{len(search_results)}: "
        f"dropped {no_price} with no price, {stale} older than {cutoff}"
    )
    return kept


@dataclass
class Observation:
    """One price read out of one source text, after validation. Carries its
    source_url so any stat built from it can be traced back to the text it came
    from, and condition_raw so the wording the page used survives even when it
    did not map onto one of the category's tiers. origin is set by code from
    where the text was fetched, never by the model - a hostile snippet can
    claim to be a price guide, but not to have been fetched from one. excluded
    names why a price was kept out of the stats, and is None for the ones that
    count."""

    price: Decimal
    tier: str
    condition_raw: str | None
    sold_or_asking: str
    source_url: str
    source_type: str = "other"
    origin: str = "search"  # search | guide
    excluded: str | None = None


async def extract_observations(
    item: str, search_results: dict[str, str], tiers: list[str], origin: str = "search"
) -> list[Observation]:
    """Read priced observations out of the search snippets in one LLM call. The
    model only parses text we already have - it never browses.

    What comes back is validated rather than trusted: it is JSON from outside
    this system, so a price that will not parse is dropped, and a tier the
    category does not have becomes "unknown" instead of silently becoming a tier
    of its own. Returns [] on any failure - grounding never takes a run down."""
    log.info(f"Extracting observations for {item} from {len(search_results)} snippets")

    prompt = await generate_price_extraction_prompt(item, search_results, tiers, EXPECTED_CURRENCY)

    try:
        response = await llm.ainvoke(prompt)
    except Exception as e:
        log.error(f"Observation extraction call failed for {item}: {e}")
        return []

    reply = response.content.strip()
    try:
        raw_observations = json.loads(reply)["observations"]
    except Exception as e:
        log.error(f"Could not parse observations for {item}: {e} - model replied: {reply}")
        return []

    allowed = set(tiers) | {"unknown"}
    observations = []
    dropped = 0
    coerced = 0

    for raw in raw_observations:
        try:
            price = Decimal(str(raw["price"]).replace(",", ""))
            source_url = raw["source_url"]
        except KeyError, TypeError, InvalidOperation:
            dropped += 1
            continue

        if not source_url:
            dropped += 1
            continue

        tier = raw.get("tier") or "unknown"
        if tier not in allowed:
            log.warning(f"Unexpected tier {tier!r} for {item}, recording as unknown")
            tier = "unknown"
            coerced += 1

        sold_or_asking = raw.get("sold_or_asking")
        if sold_or_asking not in ("sold", "asking"):
            sold_or_asking = "asking"

        source_type = raw.get("source_type")
        if source_type not in SOURCE_TYPES:
            source_type = "other"

        observations.append(
            Observation(
                price=price,
                tier=tier,
                condition_raw=raw.get("condition_raw"),
                sold_or_asking=sold_or_asking,
                source_url=source_url,
                source_type=source_type,
                origin=origin,
            )
        )

    log.info(
        f"Extracted {len(observations)} observations for {item} "
        f"(dropped {dropped} unusable, coerced {coerced} tiers to unknown)"
    )
    return observations


def strip_html(page_html: str) -> str:
    """Reduce a fetched page to plain text capped at GUIDE_PAGE_MAX_CHARS. The
    result is word soup, but extraction only needs prices and condition words
    to survive - the same job it already does on snippets, just longer."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:GUIDE_PAGE_MAX_CHARS]


def fetch_source_page(url: str) -> str | None:
    """Fetch one source page with a plain GET and reduce it to text the
    extraction prompt can read. The browser user agent is because some guide
    sites serve obvious bots a stub. Returns None on any failure - a dead
    page is a recorded miss, never a crash."""
    log.info(f"Fetching source page: {url}")
    try:
        response = requests.get(
            url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=SOURCE_FETCH_TIMEOUT_S
        )
        response.raise_for_status()
        return strip_html(response.text)
    except Exception as e:
        log.error(f"Error fetching source page {url}: {e}")
        return None


def source_fetch_plan(
    price_sources: list[dict] | None, pinned_sources: list[str] | None
) -> tuple[list[str], str | None]:
    """Decide which domains a grounding fetches: pinned first (user-owned,
    always fetched, never questioned), then trusted registry domains, deduped
    in that order. The first candidate is returned separately - it is only
    probed when the sure things come up dry, and record_source_result rotates
    probed candidates backwards so they take turns earning promotion."""
    fetch: list[str] = []
    for domain in pinned_sources or []:
        if domain not in fetch:
            fetch.append(domain)

    candidate = None
    for entry in price_sources or []:
        domain = entry.get("domain")
        if not domain or domain in fetch:
            continue
        if entry.get("status") == "trusted":
            fetch.append(domain)
        elif entry.get("status") == "candidate" and candidate is None:
            candidate = domain

    return fetch, candidate


def record_source_result(
    price_sources: list[dict] | None,
    pinned_sources: list[str] | None,
    domain: str,
    tiered_observations: int,
) -> list[dict] | None:
    """Fold one domain's fetch outcome into the registry, without mutating it.

    Dead entries are kept in the list so discovery does not re-propose them,
    and a domain still candidate afterwards rotates to the back so probes take
    turns. Pinned domains are user-owned: their failures are logged by the
    caller, never counted against them."""
    if price_sources is None or domain in (pinned_sources or []):
        return price_sources

    updated = [{**entry} for entry in price_sources]
    entry = next((e for e in updated if e.get("domain") == domain), None)
    if entry is None:
        return price_sources

    if tiered_observations >= PROMOTE_MIN_TIERED_OBS:
        entry["hits"] = entry.get("hits", 0) + 1
        entry["consecutive_misses"] = 0
        if entry.get("status") == "candidate":
            entry["status"] = "trusted"
            log.info(f"Promoted price source {domain}: parsed {tiered_observations} tiered prices")
    else:
        misses = entry.get("consecutive_misses", 0) + 1
        entry["consecutive_misses"] = misses
        starved = entry.get("status") == "candidate" and not entry.get("hits", 0)
        if misses >= DEAD_CONSECUTIVE_MISSES or (starved and misses >= CANDIDATE_DEAD_MISSES):
            entry["status"] = "dead"
            log.info(f"Demoted price source {domain} to dead after {misses} misses")

    if entry.get("status") == "candidate":
        updated.remove(entry)
        updated.append(entry)
    return updated


async def discover_price_sources(category_id: int) -> list[dict] | None:
    """Pluggable seam for source discovery: one LLM call per category proposing
    candidate guide domains. The prompt is validation-gated on the manual test
    results in docs/superpowers/guide-discovery-test-prompts.md and not built
    yet, so this returns None - the registry stays unwritten, discovery
    re-runs once the call lands, and pinned sources plus the snippet fallback
    carry grounding until then. Proposals will enter as candidates and earn
    promotion in record_source_result; the LLM's word alone never trusts a
    domain."""
    log.info(f"Source discovery not built yet for category {category_id}; pinned sources only")
    return None


async def fetch_domain_observations(
    domain: str, alias: str, item_name: str, tiers: list[str], cached_url: str | None
) -> tuple[list[Observation], str | None]:
    """One source domain's observations for one item: fetch the cached guide
    page when one is known, otherwise resolve it with a single site-scoped
    search. Returns the observations and the URL that actually answered (None
    when the domain came up dry), so the caller can cache it or drop a dead
    one."""
    url = cached_url
    text = fetch_source_page(url) if url else None
    if text is None:
        results = await search_searxng([site_query(domain, alias)], SEARXNG_URL, pages=1)
        found = pick_domain_url(results or {}, domain)
        if found and found != cached_url:
            url = found
            text = fetch_source_page(url)

    if text is None:
        return [], None
    return await extract_observations(item_name, {url: text}, tiers, origin="guide"), url


async def gather_guide_observations(
    item_id: int, item_name: str, category_id: int, tiers: list[str]
) -> list[Observation]:
    """The guide pass: fetch the category's pinned and trusted price-guide
    domains - probing one candidate when the sure things come up dry - and
    return their observations tagged origin="guide".

    All registry bookkeeping happens here: every fetch is recorded as a hit or
    miss, resolved page URLs are cached on the item, dead cached pages are
    dropped, and changed state is written back. A single domain failing is a
    recorded miss, never a crash - grounding must not take a run down."""
    sources = await get_price_sources(category_id)
    stored_registry = sources["price_sources"] if sources else None
    pinned = (sources["pinned_sources"] if sources else None) or []

    registry = stored_registry
    if sources and stored_registry is None:
        registry = await discover_price_sources(category_id)

    grounding = await get_item_grounding(item_id)
    aliases = (grounding["search_aliases"] if grounding else None) or []
    alias = aliases[0] if aliases else item_name
    stored_pages = (grounding["guide_pages"] if grounding else None) or {}
    guide_pages = dict(stored_pages)

    fetch_list, candidate = source_fetch_plan(registry, pinned)
    observations: list[Observation] = []
    productive = 0

    async def probe(domain: str) -> None:
        nonlocal registry, productive
        cached = guide_pages.get(domain)
        found, url = await fetch_domain_observations(domain, alias, item_name, tiers, cached)
        tiered = sum(1 for observation in found if observation.tier != "unknown")
        registry = record_source_result(registry, pinned, domain, tiered)
        if found:
            productive += 1
            observations.extend(found)
        if url:
            guide_pages[domain] = url
        elif cached:
            del guide_pages[domain]

    for domain in fetch_list:
        await probe(domain)
    if candidate and productive < MIN_PRODUCTIVE_DOMAINS:
        await probe(candidate)

    if sources and registry is not None and registry != stored_registry:
        await set_price_sources(category_id, registry)
    if grounding and guide_pages != stored_pages:
        await set_guide_pages(item_id, guide_pages)

    log.info(f"Guide pass for {item_name}: {len(observations)} obs from {productive} domains")
    return observations


async def collect_observations(
    item_id: int, item_name: str, category_id: int, tiers: list[str]
) -> list[Observation]:
    """The fallback ladder deciding where an item's prices come from: when the
    guide pass alone produces reportable stats, the broad template shotgun
    stays unfired - it is the fallback, not the method, and skipping it keeps
    SearXNG well under its suspension threshold.

    Outliers are quarantined before that call is made, so a transcription error
    cannot pad a tier over MIN_TIER_SAMPLE and talk the ladder out of a fallback
    the real prices needed."""
    observations = flag_outliers(
        await gather_guide_observations(item_id, item_name, category_id, tiers)
    )
    if build_market_price(tier_stats(observations), observations)["status"] == "ok":
        return observations

    log.info(f"Guide pass insufficient for {item_name}, falling back to broad snippet search")
    search_results = await search_searxng_queries(item_name, SEARXNG_URL)
    snippets = filter_snippets(search_results or {})
    if snippets:
        observations = observations + await extract_observations(item_name, snippets, tiers)
    return observations


def flag_outliers(observations: list[Observation]) -> list[Observation]:
    """Mark prices too far above their own tier to be real. Extraction reads
    prices out of prose, and a dropped decimal point turns $44.99 into $4499
    while leaving everything else about the observation intact - source, tier
    and condition wording all still look right, so distance from the tier's own
    median is the only signal left. Measured: one retailer page yielded both
    figures for the same cartridge, and the bad one set the published range.

    Only the high side is judged. A price far below its tier is a damaged copy
    or the deal we exist to find - one measured pool held a legitimate loose
    price 15x under its median - so a symmetric rule would throw away the
    findings this system is for. A tier needs MIN_TIER_SAMPLE prices before its
    median means enough to measure against; below that there is no way to tell
    which of two prices is the anomaly.

    Judged fresh every call, because the pool grows: the guide pass weighs its
    own observations, then the snippet fallback adds more and the whole pool is
    weighed again. A price the smaller pool called extreme has to be able to
    come back once the median catches up to it."""
    by_tier: dict[str, list[Observation]] = {}
    for observation in observations:
        if observation.excluded == "outlier":
            observation.excluded = None
        by_tier.setdefault(observation.tier, []).append(observation)

    for tier_observations in by_tier.values():
        if len(tier_observations) < MIN_TIER_SAMPLE:
            continue
        middle = median(sorted(observation.price for observation in tier_observations))
        if middle <= 0:
            continue
        for observation in tier_observations:
            if observation.price / middle >= OUTLIER_RATIO:
                log.info(
                    f"Quarantining {observation.price} in tier {observation.tier}: "
                    f"{observation.price / middle:.0f}x the tier median {middle} "
                    f"({observation.source_url})"
                )
                observation.excluded = "outlier"

    return observations


def tier_stats(observations: list[Observation]) -> dict[str, dict]:
    """Describe each condition tier on its own: pooled stats describe nothing
    that exists when the same cartridge is $24 loose and $14,499 graded, and
    the median resists the outliers that drag the mean ($223 vs $1,009 on one
    measured sample). Within a tier the central stats come from the best basis
    available: guide observations when any exist (an aggregated market
    statistic a pile of asking prices never outvotes by weight of numbers),
    else sold prices once there are enough (asking skews high), else all."""
    counted = [observation for observation in observations if not observation.excluded]

    by_tier: dict[str, list[Observation]] = {}
    for observation in counted:
        by_tier.setdefault(observation.tier, []).append(observation)

    stats = {}
    for tier, tier_observations in by_tier.items():
        prices = sorted(observation.price for observation in tier_observations)
        sold = sorted(
            observation.price
            for observation in tier_observations
            if observation.sold_or_asking == "sold"
        )

        guide = sorted(
            observation.price
            for observation in tier_observations
            if observation.origin == "guide" and observation.source_type == "price_guide"
        )

        if guide:
            basis_prices, basis = guide, "guide"
        elif len(sold) >= MIN_TIER_SAMPLE:
            basis_prices, basis = sold, "sold"
        else:
            basis_prices, basis = prices, "all"

        stats[tier] = {
            "median": median(basis_prices).quantize(Decimal("0.01")),
            "mean": (sum(basis_prices) / len(basis_prices)).quantize(Decimal("0.01")),
            "n": len(prices),
            "sold_n": len(sold),
            "basis": basis,
            "basis_n": len(basis_prices),
            "low": prices[0],
            "high": prices[-1],
            "prices": prices,
        }

    summary = ", ".join(
        f"{tier} n={stat['n']} ({stat['sold_n']} sold)" for tier, stat in stats.items()
    )
    log.info(f"Tier stats over {len(counted)} observations: {summary or 'none'}")

    unknown = stats.get("unknown", {}).get("n", 0)
    if unknown:
        # A high unknown rate means this category's vocabulary does not describe
        # what the sources actually say, and is the signal to regenerate it.
        log.info(f"{unknown}/{len(counted)} observations had no tier of this category")

    return stats


def build_market_price(stats: dict[str, dict], observations: list[Observation]) -> dict:
    """Shape tier stats into the market_prices payload: reportable tiers with
    prices as decimal strings, every observation as the audit trail each stat
    must be explainable from, and a confidence grade carrying the demotions
    that produced it.

    A tier is reportable when a guide anchors it - one guide value is already
    an aggregated market statistic, not a sample of one - or when it clears
    MIN_TIER_SAMPLE on its own. Without a guide anchor the demotions stack:
    snippet-only stats start at medium, and a total pool below MIN_TIER_SAMPLE
    or one with no sold prices at all (asking skews high) drops them to low.
    "insufficient" means nothing was reportable and the caller escalates.

    "unknown" is not one of those tiers. It is where extraction parks a price
    whose condition the source never stated, so it describes no state anything
    can be bought in: publishing it hands the agent a reference price for a
    condition that does not exist, and letting it vote on confidence grades the
    whole payload off a bucket no stat is drawn from. It is dropped from both,
    at both altitudes - the tier summary and the observations behind it - and
    kept in full in the audit trail, which is what it is actually good for."""
    cents = Decimal("0.01")
    reportable = {tier: stat for tier, stat in stats.items() if tier != "unknown"}
    classified = [entry for entry in observations if entry.tier != "unknown" and not entry.excluded]

    tiers = {}
    for tier, stat in reportable.items():
        if stat["basis"] != "guide" and stat["n"] < MIN_TIER_SAMPLE:
            continue
        tiers[tier] = {
            "median": str(stat["median"]),
            "mean": str(stat["mean"]),
            "low": str(stat["low"].quantize(cents)),
            "high": str(stat["high"].quantize(cents)),
            "n": stat["n"],
            "sold_n": stat["sold_n"],
            "basis": stat["basis"],
            "basis_n": stat["basis_n"],
        }

    reasons = []
    if not any(stat["basis"] == "guide" for stat in reportable.values()):
        reasons.append("no_guide_anchor")
        if len(classified) < MIN_TIER_SAMPLE:
            reasons.append(f"n={len(classified)}")
        if not any(observation.sold_or_asking == "sold" for observation in classified):
            reasons.append("all_asking")

    if not reasons:
        confidence = "high"
    elif len(reasons) == 1:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "status": "ok" if tiers else "insufficient",
        "tiers": tiers,
        "confidence": confidence,
        "confidence_reasons": reasons,
        "observations": [
            {**asdict(observation), "price": str(observation.price)} for observation in observations
        ],
    }


async def resolve_condition_tiers(category_id: int) -> list[str]:
    """Return a category's condition-tier vocabulary, generating and storing it
    on first use. Generated once, not per run: regenerating rewords the same
    tier ("cib" one run, "complete in box" the next) and splits its
    observations across both spellings."""
    category = await get_category_tiers(category_id)

    if not category:
        log.error(f"No category {category_id} found, using {DEFAULT_CONDITION_TIERS}")
        return DEFAULT_CONDITION_TIERS

    if category["condition_tiers"]:
        log.info(f"Condition tiers for {category['name']}: {category['condition_tiers']} (stored)")
        return category["condition_tiers"]

    item_names = await get_category_item_names(category_id)
    prompt = await generate_condition_tiers_prompt(category["name"], list(item_names))

    try:
        response = await llm.ainvoke(prompt)
    except Exception as e:
        log.error(f"Tier generation failed for category {category_id}: {e}")
        return DEFAULT_CONDITION_TIERS

    reply = response.content.strip()
    try:
        tiers = json.loads(reply)
    except Exception as e:
        log.error(f"Could not parse tiers for category {category_id}: {e} - replied: {reply}")
        return DEFAULT_CONDITION_TIERS

    # Checked before the write because the vocabulary is reused forever, and
    # lowercased because a stored "CIB" would never match the "cib" that
    # extraction reports back.
    if not isinstance(tiers, list) or not all(
        isinstance(tier, str) and tier.strip() for tier in tiers
    ):
        log.error(f"Tiers for category {category_id} are not a list of names: {tiers!r}")
        return DEFAULT_CONDITION_TIERS

    tiers = [tier.strip().lower() for tier in tiers]
    if not tiers:
        log.error(f"Tier generation returned no tiers for category {category_id}")
        return DEFAULT_CONDITION_TIERS

    log.info(f"Condition tiers for {category['name']}: {tiers} (generated)")
    await set_condition_tiers(category_id, tiers)
    return tiers


async def ground_item(item_id: int, item_name: str, category_id: int) -> dict:
    """Ground one item end to end: resolve its category's tier vocabulary,
    collect observations up the fallback ladder, shape them into the
    market_prices payload, and write it. Returns the payload so callers can
    log or serve it without re-reading the row."""
    tiers = await resolve_condition_tiers(category_id)
    observations = flag_outliers(await collect_observations(item_id, item_name, category_id, tiers))
    payload = build_market_price(tier_stats(observations), observations)
    await upsert_market_price(
        item_id,
        currency=EXPECTED_CURRENCY,
        tiers=payload["tiers"],
        observations=payload["observations"],
        confidence=payload["confidence"],
        confidence_reasons=payload["confidence_reasons"],
        status=payload["status"],
    )
    return payload


def select_grounding_work(candidates: list[dict], now: datetime) -> list[dict]:
    """Pick which items this run grounds, from the watched items joined to
    their market-price state. Never-grounded items come first and are exempt
    from the per-run cap, so a new item grounds on the very next invocation;
    stale items refresh oldest-first under the cap, so a big backlog catches
    up over several runs instead of stalling one. Any item attempted within
    the TTL is deferred outright - last_attempt_at moves on failure too, so a
    hard-to-ground item is not retried at full cost every run."""
    cutoff = now - timedelta(hours=MARKET_PRICE_TTL_HOURS)
    due = [
        row
        for row in candidates
        if row["last_attempt_at"] is None or row["last_attempt_at"] < cutoff
    ]
    missing = [row for row in due if row["as_of"] is None]
    stale = sorted(
        (row for row in due if row["as_of"] is not None and row["as_of"] < cutoff),
        key=lambda row: row["as_of"],
    )
    return missing + stale[:MARKET_PRICE_MAX_REFRESH_PER_RUN]


async def ground_stale(limit: int | None = None) -> int:
    """Ground every watched item whose market stats are missing or older than
    the TTL, per select_grounding_work. The explicit limit is a caller
    override on top of the per-run cap. Returns how many items grounded
    successfully; one item failing is logged and skipped - grounding must
    never take a run down."""
    candidates = await get_grounding_candidates()
    work = select_grounding_work(candidates, datetime.now(UTC))
    if limit is not None:
        work = work[:limit]
    if not work:
        log.info("Grounding: all market prices fresh, nothing to do")
        return 0

    grounded = 0
    for row in work:
        try:
            payload = await ground_item(row["item_id"], row["item_name"], row["category_id"])
        except Exception as e:
            log.error(f"Grounding failed for item {row['item_id']} ({row['item_name']}): {e}")
            continue
        grounded += 1
        log.info(f"Grounded {row['item_name']}: {payload['status']}")

    log.info(f"Grounding pass complete: {grounded}/{len(work)} items")
    return grounded
