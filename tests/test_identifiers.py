import asyncio

import pytest

from jobs.scrape_and_notify import fetch_company
from scrapers.identifiers import identifier_error
from scripts.validate_seed_schema import validate_companies


@pytest.mark.parametrize(
    "platform,ident",
    [
        ("greenhouse", "stripe"),
        ("lever", "some-co_1.io"),
        ("ashby", "Acme"),
        ("smartrecruiters", "Visa1"),
        ("workday", "3m|wd1|Search"),
        ("workday", "my7elevenhr|wd12|Careers"),
        ("teamtailor", "bmwtechworks"),
        ("teamtailor", "https://careers.eeze.com"),
        ("google", "Germany|Netherlands"),
    ],
)
def test_valid_identifiers(platform, ident):
    assert identifier_error(platform, ident) is None


@pytest.mark.parametrize(
    "platform,ident",
    [
        ("workday", "x@evil.example#|wd5|site"),  # authority injection in the tenant
        ("workday", "tenant|wd5|a/../b"),
        ("workday", "tenant|evil.com|site"),
        ("workday", "tenant|wd5"),
        ("workday", "a.b|wd5|site"),  # dots would add host labels
        ("greenhouse", "../admin"),
        ("greenhouse", "a/b"),
        ("lever", "a?x=1"),
        ("ashby", " padded "),
        ("smartrecruiters", ""),
        ("greenhouse", None),
        ("teamtailor", "http://careers.example.com"),
        ("teamtailor", "https://user:pw@x.com"),
        ("teamtailor", "Evil.com/x"),
    ],
)
def test_invalid_identifiers(platform, ident):
    assert identifier_error(platform, ident)


def test_seed_validator_rejects_hostile_workday_tenant():
    entry = {
        "company_name": "X",
        "career_url": "https://x.example",
        "ats_platform": "workday",
        "ats_identifier": "x@evil.example#|wd5|site",
    }
    errors = validate_companies([entry])
    assert errors and "invalid Workday identifier" in errors[0]


def test_fetch_company_refuses_invalid_identifier_without_requesting():
    class Boom:
        def __getattr__(self, name):  # pragma: no cover - must not be touched
            raise AssertionError("http client must not be used")

    company = {"id": 1, "name": "X", "ats_platform": "workday", "ats_identifier": "x@evil.example#|wd5|s"}
    with pytest.raises(ValueError, match="invalid ats_identifier"):
        asyncio.run(fetch_company(Boom(), company))
