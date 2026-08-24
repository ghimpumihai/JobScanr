"""Card-parsing tests using a minimal synthetic page — never commit
real careers-page HTML: it embeds third-party tokens and bloats the repo."""

from scrapers.google import CARD_RE, parse_card

SYNTHETIC_PAGE = '''
<div class="card">
  <h2>Software Engineer Intern, Summer 2027</h2>
  <span>corporate_fare</span><span>Google</span>
  <span>place</span>Munich, Germany<span>; Berlin, Germany</span><span>+2 more</span>
  <span>bar_chart</span><span>Early</span>
  <a href="jobs/results/111111111111111-software-engineer-intern-summer-2027?location=Germany"
     aria-label="Learn more about Software Engineer Intern, Summer 2027">Learn more</a>
</div>
<div class="card">
  <h2>Research Scientist PhD Intern, 2027</h2>
  <span>place</span>Zürich, Switzerland<span>; Munich, Germany</span>
  <span>bar_chart</span><span>Mid</span>
  <a href="jobs/results/222222222222222-research-scientist-phd-intern-2027?location=Germany"
     aria-label="Learn more about Research Scientist PhD Intern, 2027">Learn more</a>
</div>
'''


def _parse_all():
    cards, seen = [], set()
    for m in CARD_RE.finditer(SYNTHETIC_PAGE):
        path, title = m.group("path"), m.group("title")
        if path in seen:
            continue
        seen.add(path)
        card = parse_card(SYNTHETIC_PAGE[max(0, m.start() - 4000):m.start()], path, title)
        if card:
            cards.append(card)
    return cards


def test_parses_cards_from_synthetic_page():
    cards = _parse_all()
    assert len(cards) == 2
    swe = cards[0]
    assert swe["title"] == "Software Engineer Intern, Summer 2027"
    assert "Munich, Germany" in swe["location"]
    assert swe["url"] == ("https://www.google.com/about/careers/applications/"
                          "jobs/results/111111111111111-software-engineer-intern-summer-2027")


def test_locations_include_accented_cities():
    cards = _parse_all()
    zurich_card = [c for c in cards if "Zürich" in c["location"]]
    assert zurich_card, "accented city must survive parsing"


def test_real_page_still_parses_end_to_end():
    """Integration smoke against the live site (single polite request)."""
    import asyncio
    import httpx

    from scrapers.base import make_http_client
    from scrapers.google import GoogleClient

    async def run():
        async with make_http_client() as http:
            return await GoogleClient(http).get_jobs("Germany")

    jobs = asyncio.run(run())
    assert len(jobs) >= 10
