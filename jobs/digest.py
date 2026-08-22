"""Assemble the daily digest message (plan Phase 7)."""


def build_digest(jobs: list[dict]) -> tuple[str, str]:
    """Return (title, body) for one push notification."""
    n = len(jobs)
    title = f"{n} new matching job{'s' if n != 1 else ''}"
    top = ", ".join(f"{j['title']} @ {j['company_name']}" for j in jobs[:3])
    more = f" +{n - 3} more" if n > 3 else ""
    return title, f"{top}{more}"[:200]
