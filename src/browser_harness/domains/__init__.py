"""Virgil-agnostic browser automation domains (Slack, LinkedIn, pages, job apply)."""

from .job_apply import apply_to_job, detect_ats, load_profile, open_job_application
from .linkedin import scrape_notifications
from .pages import fetch_page_markdown
from .slack import parse_slack_archive_ts, scrape_slack_channel

__all__ = [
    "apply_to_job",
    "detect_ats",
    "fetch_page_markdown",
    "load_profile",
    "open_job_application",
    "parse_slack_archive_ts",
    "scrape_notifications",
    "scrape_slack_channel",
]
