"""Unit tests for job_apply domain."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from browser_harness.domains.job_apply import apply_to_job, detect_ats, load_profile


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://job-boards.greenhouse.io/foo/jobs/1", "greenhouse"),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/job/x", "workday"),
        ("https://jobs.ashbyhq.com/co/role", "ashby"),
        ("https://jobs.smartrecruiters.com/Co/job", "smartrecruiters"),
        ("https://www.linkedin.com/jobs/view/1", "linkedin"),
        ("https://example.com/careers", "generic"),
    ],
)
def test_detect_ats(url: str, expected: str) -> None:
    assert detect_ats(url) == expected


def test_load_profile(tmp_path) -> None:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"email": "a@b.com"}), encoding="utf-8")
    assert load_profile(p)["email"] == "a@b.com"


def test_apply_to_job_prefill_mocked() -> None:
    profile = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
    }
    with patch("browser_harness.domains.job_apply.new_tab"), patch(
        "browser_harness.domains.job_apply.wait_for_load"
    ), patch("browser_harness.domains.job_apply.time.sleep"), patch(
        "browser_harness.domains.job_apply.page_info",
        return_value={"url": "https://job-boards.greenhouse.io/x", "title": "Job"},
    ), patch("browser_harness.domains.job_apply._is_login_wall", return_value=False), patch(
        "browser_harness.domains.job_apply._has_captcha", return_value=False
    ), patch(
        "browser_harness.domains.job_apply.js",
        side_effect=[False, ["input[type=email]"], False],
    ), patch(
        "browser_harness.domains.job_apply._try_upload_resume", return_value=False
    ), patch(
        "browser_harness.domains.job_apply.capture_screenshot", return_value="/tmp/shot.png"
    ), patch("browser_harness.domains.job_apply.close_tab"), patch(
        "browser_harness.domains.job_apply.ensure_real_tab"
    ):
        result = apply_to_job("https://job-boards.greenhouse.io/x", profile)
    assert result["status"] == "prefilled"
    assert result["ats"] == "greenhouse"
    assert result["submitted"] is False
