"""Unit tests for browser_harness.domains.linkedin."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from browser_harness.domains.linkedin import (
    enrich_profile,
    name_matches,
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
            [
                {
                    "url": "https://www.linkedin.com/in/someone-else",
                    "name": "Grace Hopper",
                    "snippet": "Navy",
                },
                {
                    "url": "https://www.linkedin.com/in/ada",
                    "name": "Ada Lovelace",
                    "snippet": "Mathematician",
                },
            ],
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


def _patched_js(side_effect):
    return (
        patch("browser_harness.domains.linkedin.tab", _fake_tab),
        patch("browser_harness.domains.linkedin.wait_for_load"),
        patch("browser_harness.domains.linkedin.time.sleep"),
        patch("browser_harness.domains.linkedin.js", side_effect=side_effect),
    )


_TWO_EMMAS = [
    {
        "url": "https://www.linkedin.com/in/emma-lang-a",
        "name": "Emma Lang",
        "snippet": "Emma Lang Designer at Acme",
    },
    {
        "url": "https://www.linkedin.com/in/emma-lang-b",
        "name": "Emma Lang, MBA",
        "snippet": "Emma Lang Analyst at Globex",
    },
    {
        "url": "https://www.linkedin.com/in/emma-other",
        "name": "Emma Balling",
        "snippet": "Emma Balling",
    },
]


def test_enrich_name_only_ambiguous_does_not_guess() -> None:
    a, b, c, d = _patched_js(
        ["https://www.linkedin.com/search/results/people/?keywords=x", _TWO_EMMAS]
    )
    with a, b, c, d as js_mock:
        result = enrich_profile(name="Emma Lang")

    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "ambiguous_match"
    urls = [c["url"] for c in result["stats"]["candidates"]]
    assert urls == [
        "https://www.linkedin.com/in/emma-lang-a",
        "https://www.linkedin.com/in/emma-lang-b",
    ]
    assert js_mock.call_count == 2


def test_enrich_name_hint_disambiguates() -> None:
    profile = {
        "name": "Emma Lang, MBA",
        "headline": "Analyst",
        "about": "",
        "url": "https://www.linkedin.com/in/emma-lang-b",
    }
    a, b, c, d = _patched_js(
        [
            "https://www.linkedin.com/search/results/people/?keywords=x",
            _TWO_EMMAS,
            "https://www.linkedin.com/in/emma-lang-b",
            profile,
        ]
    )
    with a, b, c, d:
        result = enrich_profile(name="Emma Lang", hint="Globex")

    assert result["status"] == "ok"
    assert result["url"].endswith("/in/emma-lang-b")


def test_enrich_name_only_rejects_non_matching_first_hit() -> None:
    a, b, c, d = _patched_js(
        [
            "https://www.linkedin.com/search/results/people/?keywords=x",
            [_TWO_EMMAS[2]],
        ]
    )
    with a, b, c, d:
        result = enrich_profile(name="Emma Lang")

    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "no_search_match"


def test_enrich_url_with_wrong_name_is_mismatch() -> None:
    a, b, c, d = _patched_js(
        [
            "https://www.linkedin.com/in/emma-other",
            {
                "name": "Emma Balling",
                "headline": "Coach",
                "about": "",
                "url": "https://www.linkedin.com/in/emma-other",
            },
        ]
    )
    with a, b, c, d:
        result = enrich_profile(
            name="Emma Lang", url="https://www.linkedin.com/in/emma-other"
        )

    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "name_mismatch"
    assert result["stats"]["found_name"] == "Emma Balling"


def test_name_matches_folds_accents_and_order() -> None:
    assert name_matches("Jose Nunez", "Núñez José")
    assert not name_matches("Emma Lang", "Emma Balling")
    assert not name_matches("", "Anyone")


def test_scrape_notifications_exposes_profile_urls() -> None:
    batch = [
        {
            "id": "Ada viewed your profile",
            "ts": "1d",
            "text": "Ada viewed your profile",
            "links": [
                "https://www.linkedin.com/in/ada/?miniProfileUrn=x",
                "https://www.linkedin.com/feed/update/1",
            ],
        }
    ]
    a, b, c, d = _patched_js(
        ["https://www.linkedin.com/notifications/", batch, {"at_bottom": True}]
    )
    with a, b, c, d:
        result = scrape_notifications(lookback_days=3, max_scrolls=2)

    assert result["items"][0]["profile_urls"] == ["https://www.linkedin.com/in/ada"]


def test_enrich_profile_missing_args() -> None:
    result = enrich_profile()
    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "missing_args"
