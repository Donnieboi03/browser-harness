"""Unit tests for browser_harness.domains.linkedin."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from browser_harness.domains.linkedin import (
    parse_relative_age_days,
    scrape_notifications,
)


@pytest.mark.parametrize(
    ("ts", "expected"),
    [
        ("Just now", 0.0),
        ("now", 0.0),
        ("Yesterday", 1.0),
        ("2d", 2.0),
        ("3 h", 3.0 / 24.0),
        ("1w", 7.0),
        ("", None),
        ("nope", None),
    ],
)
def test_parse_relative_age_days(ts: str, expected: float | None) -> None:
    got = parse_relative_age_days(ts)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_scrape_notifications_returns_structure() -> None:
    fake_batch = [
        {
            "id": "Alice liked your post",
            "ts": "2d",
            "text": "Alice liked your post https://www.linkedin.com/jobs/view/123",
            "links": ["https://www.linkedin.com/jobs/view/123"],
        }
    ]

    with patch("browser_harness.domains.linkedin.new_tab"), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=[
            "https://www.linkedin.com/notifications/",
            fake_batch,
            {"at_bottom": True},
        ],
    ), patch("browser_harness.domains.linkedin.close_tab"), patch(
        "browser_harness.domains.linkedin.ensure_real_tab"
    ):
        result = scrape_notifications(lookback_days=3, max_scrolls=5)

    assert result["stats"]["unique_items"] == 1
    assert "linkedin.com/jobs" in result["links"][0]
    assert result["stats"]["stopped_reason"] == "scroll_bottom"
    assert "Alice" in result["markdown"]


def test_scrape_notifications_login_wall() -> None:
    with patch("browser_harness.domains.linkedin.new_tab"), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        return_value="https://www.linkedin.com/login",
    ), patch("browser_harness.domains.linkedin.close_tab"), patch(
        "browser_harness.domains.linkedin.ensure_real_tab"
    ):
        result = scrape_notifications()

    assert result["stats"]["stopped_reason"] == "login_required"
    assert result["markdown"] == ""
