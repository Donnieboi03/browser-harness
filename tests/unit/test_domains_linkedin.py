"""Unit tests for browser_harness.domains.linkedin."""
from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from browser_harness.domains.linkedin import (
    PROFILE_EXTRACT_JS,
    clean_name,
    current_position,
    enrich_profile,
    name_matches,
    parse_experience,
    parse_ld_person,
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


@pytest.mark.parametrize("raw,clean", [
    ("Ada Lovelace (she/her)", "Ada Lovelace"),
    ("Grace Hopper 🚀, PhD", "Grace Hopper"),
    ("Alan Turing, OBE, FRS", "Alan Turing"),
    ("Linus Torvalds MBA", "Linus Torvalds"),
    ("José García", "José García"),
    ("Mary-Jane Watson ✨", "Mary-Jane Watson"),
    ("Kim Lee, Head of Growth", "Kim Lee, Head of Growth"),
])
def test_clean_name(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


def test_parse_ld_person_reads_graph() -> None:
    blob = json.dumps({"@graph": [
        {"@type": "WebPage"},
        {"@type": "Person", "jobTitle": ["Staff Engineer"],
         "worksFor": [{"@type": "Organization", "name": "Acme", "url": "https://www.linkedin.com/company/acme"}]},
    ]})
    assert parse_ld_person(["not json", blob]) == {
        "title": "Staff Engineer", "company": "Acme", "company_url": "https://www.linkedin.com/company/acme",
    }


def test_parse_experience_single_role_layout() -> None:
    lines = ["Experience", "Senior Engineer", "Senior Engineer", "Acme · Full-time",
             "Jan 2022 - Present · 2 yrs 3 mos", "San Francisco"]
    links = [{"url": "https://www.linkedin.com/company/acme/", "text": "Acme"}]
    assert parse_experience(lines, links) == {
        "title": "Senior Engineer", "company": "Acme", "company_url": "https://www.linkedin.com/company/acme/",
    }


def test_parse_experience_grouped_layout() -> None:
    lines = ["Experience", "Acme", "Full-time · 3 yrs", "Staff Engineer", "Jan 2024 - Present · 1 yr",
             "Senior Engineer", "2021 - 2024"]
    assert parse_experience(lines) == {"title": "Staff Engineer", "company": "Acme", "company_url": ""}


def test_parse_experience_without_employment_type() -> None:
    assert parse_experience(["Engineer", "Acme", "2020 - Present"])["company"] == "Acme"
    assert parse_experience(["Experience"]) == {}


def test_current_position_prefers_ld_then_experience_then_headline() -> None:
    raw = {"ld_json": [json.dumps({"@type": "Person", "jobTitle": "CTO"})],
           "experience_lines": ["Founder", "Beta Inc · Full-time"]}
    assert current_position(raw) == {"title": "CTO", "company": "Beta Inc"}
    assert current_position({}, "Product Designer at Figma | ex-Google") == {
        "title": "Product Designer", "company": "Figma",
    }
    assert current_position({}, "Builder of things") == {}


def test_enrich_profile_returns_position_and_clean_name() -> None:
    profile = {
        "name": "Ada Lovelace (she/her)",
        "headline": "Mathematician",
        "about": "First programmer",
        "experience_lines": ["Experience", "Analyst", "Analytical Engine Co · Full-time", "1842 - Present"],
        "company_links": [{"url": "https://www.linkedin.com/company/aec/", "text": "Analytical Engine Co"}],
        "url": "https://www.linkedin.com/in/ada",
    }
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=["https://www.linkedin.com/in/ada", profile],
    ):
        result = enrich_profile(url="https://www.linkedin.com/in/ada", name="Ada Lovelace")

    assert result["name_clean"] == "Ada Lovelace"
    assert result["current_position"] == {
        "title": "Analyst", "company": "Analytical Engine Co",
        "company_url": "https://www.linkedin.com/company/aec/",
    }
    assert "Current: Analyst at Analytical Engine Co" in result["markdown"]


def test_profile_extract_js_reads_ld_json_and_experience_lines() -> None:
    assert "application/ld+json" in PROFILE_EXTRACT_JS
    assert "experience_lines" in PROFILE_EXTRACT_JS and "/company/" in PROFILE_EXTRACT_JS


def test_enrich_profile_404_is_not_found() -> None:
    with patch("browser_harness.domains.linkedin.tab", _fake_tab), patch(
        "browser_harness.domains.linkedin.wait_for_load"
    ), patch("browser_harness.domains.linkedin.time.sleep"), patch(
        "browser_harness.domains.linkedin.js",
        side_effect=[
            "https://www.linkedin.com/404/",
            {"name": "", "headline": "", "about": "", "url": "https://www.linkedin.com/404/"},
        ],
    ):
        result = enrich_profile(name="Ada Lovelace", url="https://www.linkedin.com/in/ada")

    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "not_found"


def test_profile_extract_js_has_title_and_h2_fallbacks() -> None:
    from browser_harness.domains.linkedin import PROFILE_EXTRACT_JS

    assert "document.title" in PROFILE_EXTRACT_JS
    assert "headlineAfterName" in PROFILE_EXTRACT_JS


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


def test_scrape_notifications_pairs_names_with_decoded_profile_urls() -> None:
    batch = [
        {
            "id": "Sabrina reacted",
            "ts": "1d",
            "text": "Sabrina Burka reacted to your post",
            "links": ["https://www.linkedin.com/in/sabrina%2Dburka"],
            "people": [
                {"url": "https://www.linkedin.com/in/sabrina%2Dburka", "name": "Sabrina Burka"},
                {"url": "https://www.linkedin.com/in/sabrina-burka/", "name": ""},
            ],
        }
    ]
    a, b, c, d = _patched_js(
        ["https://www.linkedin.com/notifications/", batch, {"at_bottom": True}]
    )
    with a, b, c, d:
        result = scrape_notifications(lookback_days=3, max_scrolls=2)

    item = result["items"][0]
    assert item["profile_urls"] == ["https://www.linkedin.com/in/sabrina-burka"]
    assert item["people"] == [
        {"name": "Sabrina Burka", "url": "https://www.linkedin.com/in/sabrina-burka"}
    ]


def test_extract_js_targets_modern_cards_and_relative_links() -> None:
    from browser_harness.domains.linkedin import EXTRACT_JS

    assert "notification-card-container" in EXTRACT_JS
    assert "a[href^=\"http\"]" not in EXTRACT_JS
    assert 'div[class*="notification"]' not in EXTRACT_JS


def test_enrich_profile_missing_args() -> None:
    result = enrich_profile()
    assert result["status"] == "error"
    assert result["stats"]["stopped_reason"] == "missing_args"
