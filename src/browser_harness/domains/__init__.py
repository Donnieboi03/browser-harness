"""Virgil-agnostic browser automation domains (Slack, LinkedIn, pages, job apply)."""

from .job_apply import apply_to_job, detect_ats, load_profile
from .linkedin import enrich_profile, scrape_notifications
from .slack import parse_slack_archive_ts, scrape_slack_channel


def fetch_page_markdown(*args, **kwargs):
    """Lazy import — pages depends on crawl4ai injected at CLI runtime."""
    from .pages import fetch_page_markdown as _fetch

    return _fetch(*args, **kwargs)


__all__ = [
    "apply_to_job",
    "detect_ats",
    "enrich_profile",
    "fetch_page_markdown",
    "load_profile",
    "parse_slack_archive_ts",
    "scrape_notifications",
    "scrape_slack_channel",
]
