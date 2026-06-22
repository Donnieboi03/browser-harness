"""Job application prefill via logged-in Chrome (prefill-only by default)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from browser_harness.helpers import (
    capture_screenshot,
    close_tab,
    ensure_real_tab,
    js,
    new_tab,
    page_info,
    upload_file,
    wait_for_load,
)

_LOGIN_HINTS = ("login", "signin", "sign-in", "auth", "oauth")
_BLOCKED_SELECTORS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "challenge",
)


def detect_ats(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "myworkdayjobs.com" in host:
        return "workday"
    if "ashbyhq.com" in host:
        return "ashby"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "linkedin.com" in host:
        return "linkedin"
    return "generic"


def load_profile(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Profile not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _is_login_wall(url: str) -> bool:
    lower = url.lower()
    return any(h in lower for h in _LOGIN_HINTS)


def _has_captcha() -> bool:
    return bool(
        js(
            f"""(() => {{
      const html = document.documentElement.innerHTML.toLowerCase();
      return {_BLOCKED_SELECTORS!r}.some(s => html.includes(s));
    }})()"""
        )
    )


CLICK_APPLY_JS = """(() => {
  const labels = ['apply', 'apply now', 'submit application', 'i\\'m interested'];
  const candidates = [...document.querySelectorAll('a, button, [role="button"]')];
  for (const el of candidates) {
    const text = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
    if (labels.some(l => text === l || text.startsWith(l))) {
      el.click();
      return true;
    }
  }
  return false;
})()"""


FILL_FIELDS_JS = """(profile) => {
  const filled = [];
  const setVal = (el, val) => {
    if (!el || val == null || val === '') return;
    el.focus();
    el.value = val;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const tryFill = (selectors, val) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) { setVal(el, val); filled.push(sel); return true; }
    }
    return false;
  };
  tryFill(['input[name="first_name"]', 'input#first_name', 'input[name*="first" i]'], profile.first_name);
  tryFill(['input[name="last_name"]', 'input#last_name', 'input[name*="last" i]'], profile.last_name);
  tryFill(['input[type="email"]', 'input[name="email"]', 'input#email'], profile.email);
  tryFill(['input[type="tel"]', 'input[name="phone"]', 'input#phone'], profile.phone);
  tryFill(['input[name="urls[LinkedIn]"]', 'input[name*="linkedin" i]'], profile.linkedin_url);
  tryFill(['input[name="urls[GitHub]"]', 'input[name*="github" i]'], profile.github_url);
  tryFill(['input[name*="location" i]', 'input#location'], profile.location);
  if (profile.custom_answers) {
    for (const [needle, answer] of Object.entries(profile.custom_answers)) {
      const labels = [...document.querySelectorAll('label')];
      for (const lab of labels) {
        if ((lab.innerText || '').toLowerCase().includes(needle.toLowerCase())) {
          const id = lab.getAttribute('for');
          const input = id ? document.getElementById(id) : lab.querySelector('input, textarea, select');
          if (input) { setVal(input, answer); filled.push('custom:' + needle); }
        }
      }
    }
  }
  return filled;
}"""


def _try_upload_resume(profile: dict[str, Any]) -> bool:
    resume = profile.get("resume_path")
    if not resume or not Path(str(resume)).is_file():
        return False
    selectors = [
        'input[type="file"]',
        'input[type="file"][name*="resume" i]',
        'input[type="file"][id*="resume" i]',
    ]
    for sel in selectors:
        try:
            upload_file(sel, str(resume))
            return True
        except Exception:
            continue
    return False


def _maybe_submit(submit: bool) -> bool:
    if not submit:
        return False
    return bool(
        js(
            """(() => {
      const labels = ['submit', 'submit application', 'apply', 'send application'];
      const candidates = [...document.querySelectorAll('button, [type="submit"], [role="button"]')];
      for (const el of candidates) {
        const text = (el.innerText || el.value || '').trim().toLowerCase();
        if (labels.some(l => text.includes(l))) { el.click(); return true; }
      }
      return false;
    })()"""
        )
    )


def apply_to_job(url: str, profile: dict[str, Any], *, submit: bool = False) -> dict[str, Any]:
    """Open job URL, prefill application fields, optionally submit."""
    ats = detect_ats(url)
    fields_filled: list[str] = []
    status = "prefilled"

    new_tab(url)
    wait_for_load()
    time.sleep(2.5)

    info = page_info()
    current_url = info.get("url") or url

    if _is_login_wall(current_url) or _has_captcha():
        shot = capture_screenshot(max_dim=1600)
        try:
            close_tab()
        except Exception:
            pass
        ensure_real_tab()
        return {
            "status": "blocked",
            "ats": ats,
            "url": current_url,
            "fields_filled": [],
            "blocked_reason": "login_required" if _is_login_wall(current_url) else "captcha",
            "screenshot_path": shot,
            "submitted": False,
        }

    if ats in {"greenhouse", "workday", "ashby", "smartrecruiters", "generic"}:
        js(CLICK_APPLY_JS)
        time.sleep(2)
        filled = js(f"({FILL_FIELDS_JS})({json.dumps(profile)})")
        if isinstance(filled, list):
            fields_filled.extend(str(x) for x in filled)
        if _try_upload_resume(profile):
            fields_filled.append("resume_upload")

    if ats == "linkedin":
        filled = js(f"({FILL_FIELDS_JS})({json.dumps(profile)})")
        if isinstance(filled, list):
            fields_filled.extend(str(x) for x in filled)
        submit = False

    submitted = _maybe_submit(submit)
    if submitted:
        status = "submitted"
        time.sleep(1.5)

    shot = capture_screenshot(max_dim=1600)
    try:
        close_tab()
    except Exception:
        pass
    ensure_real_tab()

    return {
        "status": status,
        "ats": ats,
        "url": current_url,
        "fields_filled": fields_filled,
        "blocked_reason": None,
        "screenshot_path": shot,
        "submitted": submitted,
    }


def run_apply_job_cli(argv: list[str]) -> int:
    """``browser-harness apply-job --url URL --profile PATH [--submit]``"""
    import argparse

    parser = argparse.ArgumentParser(prog="browser-harness apply-job")
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--submit", action="store_true")
    ns = parser.parse_args(argv)
    profile = load_profile(ns.profile)
    result = apply_to_job(ns.url, profile, submit=ns.submit)
    print(json.dumps(result))
    return 0 if result.get("status") != "error" else 1
