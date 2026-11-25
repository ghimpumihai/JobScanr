"""Stage 2 input for the remote-browser apply spike (#129, Task 6.2): picks recent postings per ATS from the
database (read-only) and builds Greenhouse fill plans for a fake person, so the runner can measure screening
questions too. Live: one public GET per Greenhouse posting (`?questions=true`), paced. Writes a JSON file.

Usage:
  python -m scripts.spike_postings --confirm-live --out web/.spike-results/postings.json
"""

import argparse
import asyncio
import json
import logging
import random
import sys
from itertools import zip_longest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from db import queries
from jobs.apply.fill_plan import build_plan, greenhouse_form_url
from jobs.apply.greenhouse import GreenhouseSubmitter

logger = logging.getLogger(__name__)

SAMPLE = {"greenhouse": 30, "lever": 15, "ashby": 15}
PER_COMPANY = 3  # spread the sample across employers
# Fake person: example.com is reserved, and the phone number is in Ofcom's range for drama.
PERSONA = {
    "id": 0,
    "auth_user_id": "spike",
    "email": "jane.doe.test@example.com",
    "resume_data": {"phone": "+44 7700 900000", "location": "London, UK", "urls": {}},
    "profile_filters": {},
    "screening_defaults": {
        "full_name": "Jane Doe",
        "work_authorization": True,
        "requires_sponsorship": False,
        "years_experience": 1,
        "notice_period_days": 30,
    },
}


def pick(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Up to n rows, at most PER_COMPANY per company, in a seeded random order."""
    rng = random.Random(seed)
    rows = rows[:]
    rng.shuffle(rows)
    per: dict[str, int] = {}
    out = []
    for r in rows:
        if per.get(r["ats_identifier"], 0) < PER_COMPANY:
            per[r["ats_identifier"]] = per.get(r["ats_identifier"], 0) + 1
            out.append(r)
        if len(out) == n:
            break
    return out


def recent_postings(platform: str) -> list[dict]:
    with queries.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT jp.url, jp.external_id, c.ats_identifier
            FROM job_postings jp JOIN companies c ON c.id = jp.company_id
            WHERE c.ats_platform = %s AND jp.last_seen_at > NOW() - INTERVAL '2 days'
            """,
            (platform,),
        )
        return [{"url": r[0], "external_id": r[1], "ats_identifier": r[2]} for r in cur.fetchall()]


async def with_plans(postings: list[dict]) -> None:
    """Adds `plan` to each Greenhouse posting in place; a failed GET leaves plan None. One request at a time."""
    async with httpx.AsyncClient() as client:
        submitter = GreenhouseSubmitter(client)
        for p in postings:
            if p["platform"] != "greenhouse":
                continue
            posting = {**p, "ats_platform": "greenhouse"}
            try:
                questions = await submitter.fetch_questions(posting)  # type: ignore[arg-type]
                p["plan"] = build_plan(questions, PERSONA, greenhouse_form_url(posting))  # type: ignore[arg-type]
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("No plan for %s: %s", p["url"], exc)
            await asyncio.sleep(1)


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Pick stage 2 postings and build fill plans (#129).")
    parser.add_argument("--confirm-live", action="store_true", help="required: fetches Greenhouse question schemas")
    parser.add_argument("--out", required=True, help="JSON file to write")
    parser.add_argument("--seed", type=int, default=129)
    args = parser.parse_args()
    if not args.confirm_live:
        logger.error("Refusing to run without --confirm-live (sends one GET per Greenhouse posting).")
        return 2
    config.load_environment()

    per_platform = [
        [{**r, "platform": platform, "plan": None} for r in pick(recent_postings(platform), n, args.seed)]
        for platform, n in SAMPLE.items()
    ]
    # Interleaved, so the runner's --limit 3 tries one posting of each platform.
    postings = [p for group in zip_longest(*per_platform) for p in group if p]
    asyncio.run(with_plans(postings))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(postings, indent=1))
    counts = {pl: sum(p["platform"] == pl for p in postings) for pl in SAMPLE}
    logger.info("Wrote %d postings %s to %s", len(postings), counts, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
