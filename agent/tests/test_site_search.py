"""Site-scoped search plumbing: query construction and picking the result
that is actually on the queried domain — site: queries can leak other hosts."""

from pricing import pick_domain_url, site_query


def test_site_query_scopes_the_alias_to_the_domain():
    assert site_query("pricecharting.com", "pokemon emerald gba") == (
        "site:pricecharting.com pokemon emerald gba"
    )


class TestPickDomainUrl:
    def test_first_result_on_the_domain_wins(self):
        results = {
            "https://www.pricecharting.com/game/gba/pokemon-emerald": "a",
            "https://www.pricecharting.com/other": "b",
        }
        url = pick_domain_url(results, "pricecharting.com")
        assert url == "https://www.pricecharting.com/game/gba/pokemon-emerald"

    def test_leaked_foreign_hosts_are_skipped(self):
        results = {
            "https://www.reddit.com/r/gba/emerald": "chatter",
            "https://pricecharting.com/game/gba/pokemon-emerald": "guide",
        }
        assert pick_domain_url(results, "pricecharting.com") == (
            "https://pricecharting.com/game/gba/pokemon-emerald"
        )

    def test_subdomains_count_lookalike_hosts_do_not(self):
        assert pick_domain_url({"https://gba.pricecharting.com/x": ""}, "pricecharting.com")
        assert pick_domain_url({"https://notpricecharting.com/x": ""}, "pricecharting.com") is None

    def test_no_match_returns_none(self):
        assert pick_domain_url({}, "pricecharting.com") is None
