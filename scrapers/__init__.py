"""ATS client registry."""

from scrapers.ashby import AshbyClient
from scrapers.base import BaseClient
from scrapers.google import GoogleClient
from scrapers.greenhouse import GreenhouseClient
from scrapers.lever import LeverClient
from scrapers.smartrecruiters import SmartRecruitersClient
from scrapers.teamtailor import TeamtailorClient
from scrapers.workday import WorkdayClient

CLIENTS: dict[str, type[BaseClient]] = {
    "workday": WorkdayClient,
    "google": GoogleClient,
    "greenhouse": GreenhouseClient,
    "ashby": AshbyClient,
    "lever": LeverClient,
    "teamtailor": TeamtailorClient,
    "smartrecruiters": SmartRecruitersClient,
}


def get_client(platform: str, http) -> BaseClient:
    try:
        return CLIENTS[platform](http)
    except KeyError:
        raise ValueError(f"no scraper registered for platform '{platform}'")
