"""Unit tests for browser_harness.domains.linkedin."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from browser_harness.domains.linkedin import (
    enrich_profile,
    parse_relative_age_days,
    scrape_notifications,
)


@contextmanager
def _fake_tab(_url: str = "about:blank"):
    yield "tid"


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

    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=[
            "https://www.linkedin.com/notifications/",
            fake_batch,
            {"at_bottom": True},
        ],
    ):
        result = scrape_notifications(lookback_days=3, max_scrolls=5)

    assert result["stats"]["unique_items"] == 1
    assert "linkedin.com/jobs" in result["links"][0]
    assert result["stats"]["stopped_reason"] == "scroll_bottom"
    assert "Alice" in result["markdown"]


def test_scrape_notifications_login_wall() -> None:
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        return_value="https://www.linkedin.com/login",
    ):
        result = scrape_notifications()

    assert result["stats"]["stopped_reason"] == "login_required"
    assert result["markdown"] == ""


def test_enrich_profile_by_url() -> None:
    profile = {
        "name": "Ada Lovelace",
        "headline": "Mathematician",
        "about": "First programmer",
        "location": "London",
        "experience_snip": "Analytical Engine",
        "url": "https://www.linkedin.com/in/ada",
    }
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=[
            "https://www.linkedin.com/in/ada",
            profile,
        ],
    ):
        result = enrich_profile(url="https://www.linkedin.com/in/ada")

    assert result["status"] == "ok"
    assert result["name"] == "Ada Lovelace"
    assert result["headline"] == "Mathematician"
    assert result["about"] == "First programmer"
    assert result["location"] == "London"
    assert "Ada" in result["markdown"]


def test_enrich_profile_search_then_open() -> None:
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=[
            "https://www.linkedin.com/search/results/people/?keywords=Ada",
            {
                "urls": ["https://www.linkedin.com/in/ada"],
                "best": "https://www.linkedin.com/in/ada",
            },
            "https://www.linkedin.com/in/ada",
            {
                "name": "Ada Lovelace",
                "headline": "Mathematician",
                "about": "Notes",
                "location": "",
                "experience_snip": "",
                "url": "https://www.linkedin.com/in/ada",
            },
        ],
    ):
        result = enrich_profile(name="Ada Lovelace")

    assert result["status"] == "ok"
    assert result["url"].endswith("/in/ada")
    assert result["name"] == "Ada Lovelace"


def test_enrich_profile_login_wall_awaiting() -> None:
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        return_value="https://www.linkedin.com/login",
    ):
        result = enrich_profile(
            url="https://www.linkedin.com/in/ada",
            allow_login_resume=True,
        )

    assert result["status"] == "awaiting_credentials"
    assert result["login"]["site"] == "linkedin.com"


def test_enrich_profile_missing_args() -> None:
    result = enrich_profile()
    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "missing_args"
