"""ATS client registry."""

from scrapers.base import BaseClient
from scrapers.ashby import AshbyClient
from scrapers.greenhouse import GreenhouseClient
from scrapers.lever import LeverClient
from scrapers.workday import WorkdayClient

CLIENTS: dict[str, type[BaseClient]] = {
    "workday": WorkdayClient,
    "greenhouse": GreenhouseClient,
    "ashby": AshbyClient,
    "lever": LeverClient,
}


def get_client(platform: str, http) -> BaseClient:
    try:
        return CLIENTS[platform](http)
    except KeyError:
        raise ValueError(f"no scraper registered for platform '{platform}'")
