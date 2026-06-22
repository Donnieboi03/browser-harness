"""Virgil-agnostic browser automation domains (Slack, pages, job apply)."""

from .pages import fetch_page_markdown
from .slack import parse_slack_archive_ts, scrape_slack_channel

__all__ = [
    "fetch_page_markdown",
    "parse_slack_archive_ts",
    "scrape_slack_channel",
]
