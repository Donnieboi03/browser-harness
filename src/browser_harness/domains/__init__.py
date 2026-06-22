"""Virgil-agnostic browser automation domains (Slack, pages, job apply)."""

from .job_apply import apply_to_job, detect_ats, load_profile
from .pages import fetch_page_markdown
from .slack import parse_slack_archive_ts, scrape_slack_channel

__all__ = [
    "apply_to_job",
    "detect_ats",
    "fetch_page_markdown",
    "load_profile",
    "parse_slack_archive_ts",
    "scrape_slack_channel",
]
