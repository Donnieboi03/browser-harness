"""Unit tests for browser_harness.domains.slack."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from browser_harness.domains.slack import parse_slack_archive_ts, scrape_slack_channel


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (
            "https://colorstack.slack.com/archives/C011/p1781321112539969",
            1781321112.539969,
        ),
        ("https://x.slack.com/archives/C/p123456", 123456.0),
        ("https://example.com/no-ts", None),
    ],
)
def test_parse_slack_archive_ts(href: str, expected: float | None) -> None:
    assert parse_slack_archive_ts(href) == expected


def test_scrape_slack_channel_returns_structure() -> None:
    fake_batch = [
        {
            "id": "https://x.slack.com/archives/C/p1781321112539969",
            "ts": "9:00",
            "ts_unix": 1781321112.539969,
            "text": "Hello https://example.com/job",
            "links": ["https://example.com/job"],
        }
    ]

    with patch("browser_harness.domains.slack.new_tab"), patch(
        "browser_harness.domains.slack.wait_for_load"
    ), patch("browser_harness.domains.slack.time.sleep"), patch(
        "browser_harness.domains.slack.js", side_effect=[fake_batch, {"at_top": True}]
    ), patch("browser_harness.domains.slack.close_tab"), patch(
        "browser_harness.domains.slack.ensure_real_tab"
    ):
        result = scrape_slack_channel(
            "https://app.slack.com/client/T/C",
            lookback_days=14,
            scrolls_per_day=2,
        )

    assert result["stats"]["unique_messages"] == 1
    assert "example.com/job" in result["links"][0]
    assert result["stats"]["stopped_reason"] == "scroll_top"
    assert "Hello" in result["markdown"]
