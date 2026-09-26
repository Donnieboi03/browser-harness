"""LinkedIn notifications scrape + profile enrich via logged-in Chrome."""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any
from urllib.parse import quote_plus

from browser_harness.helpers import (
    js,
    tab,
    wait_for_load,
)

DEFAULT_NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"
SEARCH_PEOPLE_URL = (
    "https://www.linkedin.com/search/results/people/?keywords={keywords}"
)
_PROFILE_PATH_RE = re.compile(
    r"https?://(?:[\w.-]+\.)?linkedin\.com/in/[\w%-]+/?",
    re.IGNORECASE,
)

SEARCH_CANDIDATES_JS = """(() => {
  const byUrl = new Map();
  for (const a of document.querySelectorAll('a[href*="/in/"]')) {
    const url = (a.href || '').split('?')[0].replace(/\\/$/, '');
    if (!/linkedin\\.com\\/in\\//i.test(url)) continue;
    const key = url.toLowerCase();
    const span = a.querySelector('span[aria-hidden="true"]');
    const name = ((span ? span.innerText : a.innerText) || '')
      .split('\\n')[0].trim();
    const box = a.closest(
      'li, [data-chameleon-result-urn], [data-view-name*="search-entity"]'
    ) || a.parentElement;
    const snippet = ((box && box.innerText) || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 300);
    const prev = byUrl.get(key);
    if (!prev) {
      byUrl.set(key, { url, name, snippet });
    } else if (!prev.name && name) {
      prev.name = name;
    }
  }
  return [...byUrl.values()].slice(0, 10);
})()"""

PROFILE_EXTRACT_JS = """(() => {
  const textOf = (sel) => {
    const el = document.querySelector(sel);
    return el ? (el.innerText || '').trim().replace(/\\s+/g, ' ') : '';
  };
  const name =
    textOf('h1') ||
    textOf('.text-heading-xlarge') ||
    textOf('[data-anonymize="person-name"]');
  const headline =
    textOf('.text-body-medium.break-words') ||
    textOf('[data-generated-suggestion-target]') ||
    textOf('.pv-text-details__left-panel .text-body-medium');
  let about = '';
  const aboutHeader = [...document.querySelectorAll('h2, section')]
    .find(el => /\\babout\\b/i.test(el.innerText || ''));
  if (aboutHeader) {
    const section = aboutHeader.closest('section') || aboutHeader.parentElement;
    if (section) {
      about = (section.innerText || '')
        .replace(/^about\\s*/i, '')
        .trim()
        .replace(/\\s+/g, ' ')
        .slice(0, 1200);
    }
  }
  const location =
    textOf('.text-body-small.inline.t-black--light.break-words') ||
    textOf('span.text-body-small.inline.t-black--light') ||
    '';
  let experience = '';
  const expSection = [...document.querySelectorAll('section')]
    .find(el => /\\bexperience\\b/i.test(
      (el.querySelector('h2') || {}).innerText || ''
    ));
  if (expSection) {
    experience = (expSection.innerText || '')
      .trim()
      .replace(/\\s+/g, ' ')
      .slice(0, 800);
  }
  return {
    name,
    headline,
    about,
    location,
    experience_snip: experience,
    url: window.location.href || '',
  };
})()"""

# Relative age → days (best-effort; LinkedIn shows "2d", "3h", "1w", "Yesterday").
_REL_RE = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>mo|w|d|h|m|s)\b|"
    r"\byesterday\b|"
    r"\bjust\s+now\b|"
    r"\bnow\b",
    re.IGNORECASE,
)

SCROLL_JS = """(() => {
  const before = window.scrollY || document.documentElement.scrollTop || 0;
  const maxY = Math.max(
    document.body.scrollHeight,
    document.documentElement.scrollHeight
  ) - window.innerHeight;
  window.scrollBy(0, Math.floor(window.innerHeight * 0.9));
  const after = window.scrollY || document.documentElement.scrollTop || 0;
  return {
    ok: true,
    before,
    after,
    at_bottom: after >= maxY - 8 || after === before,
  };
})()"""

EXTRACT_JS = """(() => {
  const skipHost = (h) =>
    /linkedin\\.com\\/(help|legal|uas\\/login|checkpoint)/i.test(h || '');
  const cards = [];
  const roots = [
    ...document.querySelectorAll(
      '[data-finite-scroll-hotkey-item], ' +
      'div.nt-card, article, ' +
      'li.notification-card, ' +
      'div[class*="notification"]'
    ),
  ];
  const seen = new Set();
  for (const el of roots) {
    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
    if (!text || text.length < 12) continue;
    const key = text.slice(0, 160);
    if (seen.has(key)) continue;
    seen.add(key);
    const links = [...el.querySelectorAll('a[href^="http"]')]
      .map(a => a.href)
      .filter(h => h && !skipHost(h) && !h.includes('/notifications'));
    // Prefer short relative-time nodes when present
    let ts = '';
    const timeEl = el.querySelector('time, .time-ago, span[class*="time"]');
    if (timeEl) ts = (timeEl.innerText || timeEl.getAttribute('datetime') || '').trim();
    if (!ts) {
      const m = text.match(/\\b(\\d+\\s*(?:mo|w|d|h|m|s)|Yesterday|Just now)\\b/i);
      if (m) ts = m[0];
    }
    cards.push({
      id: key,
      ts,
      text: text.slice(0, 900),
      links: [...new Set(links)].slice(0, 8),
    });
  }
  return cards;
})()"""


def parse_relative_age_days(ts: str) -> float | None:
    """Best-effort age in days from LinkedIn-style relative timestamps."""
    raw = (ts or "").strip().lower()
    if not raw:
        return None
    if "just now" in raw or raw == "now":
        return 0.0
    if "yesterday" in raw:
        return 1.0
    m = _REL_RE.search(raw)
    if not m:
        return None
    if m.group(0).lower() in {"yesterday"} or "yesterday" in m.group(0).lower():
        return 1.0
    num_s = m.group("num")
    unit = (m.group("unit") or "").lower()
    if not num_s or not unit:
        return None
    num = float(num_s)
    if unit == "mo":
        return num * 30.0
    if unit == "w":
        return num * 7.0
    if unit == "d":
        return num
    if unit == "h":
        return num / 24.0
    if unit == "m":
        return num / (24.0 * 60.0)
    if unit == "s":
        return num / (24.0 * 3600.0)
    return None


def _dedupe_links(items: dict[str, dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items.values():
        for link in item.get("links") or []:
            normalized = link.split("?")[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(link)
    return out


def scrape_notifications(
    url: str = DEFAULT_NOTIFICATIONS_URL,
    *,
    lookback_days: int = 3,
    max_scrolls: int = 15,
    boot_wait_sec: float = 4.0,
    scroll_pause_sec: float = 0.8,
    allow_login_resume: bool = False,
) -> dict[str, Any]:
    """Open LinkedIn notifications, scroll, return markdown + links.

    Same return contract as ``slack.scrape_slack_channel`` so Virgil
    ``browser_source`` can consume it unchanged.
    """
    lookback_days = max(1, min(int(lookback_days), 30))
    max_scrolls = max(1, min(int(max_scrolls), 40))
    cutoff_days = float(lookback_days)

    with tab(url):
        wait_for_load()
        time.sleep(boot_wait_sec)

        href = js("location.href") or ""
        if isinstance(href, str) and ("/login" in href or "/checkpoint" in href or "/uas/" in href):
            if allow_login_resume:
                return {
                    "status": "awaiting_credentials",
                    "markdown": "",
                    "items": [],
                    "links": [],
                    "login": {
                        "site": "linkedin.com",
                        "url": href,
                        "rationale": "LinkedIn notifications scrape hit login wall",
                        "fields": ["username", "password"],
                    },
                    "checkpoint": {"step": "post_nav", "resume_url": url},
                    "stats": {
                        "scroll_passes": 0,
                        "unique_items": 0,
                        "stopped_reason": "login_required",
                        "lookback_days": lookback_days,
                        "max_scrolls": max_scrolls,
                        "url": href,
                    },
                }
            return {
                "markdown": "",
                "items": [],
                "links": [],
                "stats": {
                    "scroll_passes": 0,
                    "unique_items": 0,
                    "stopped_reason": "login_required",
                    "lookback_days": lookback_days,
                    "max_scrolls": max_scrolls,
                    "url": href,
                },
            }

        seen: dict[str, dict[str, Any]] = {}
        stopped_reason = "max_scrolls"
        scroll_passes = 0

        for _ in range(max_scrolls):
            batch = js(EXTRACT_JS) or []
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                seen[str(item["id"])] = item

            ages = [
                parse_relative_age_days(str(m.get("ts") or ""))
                for m in seen.values()
            ]
            ages = [a for a in ages if a is not None]
            if ages and max(ages) >= cutoff_days and len(seen) >= 3:
                oldest = max(ages)
                if oldest >= cutoff_days:
                    stopped_reason = "lookback_reached"
                    break

            scroll_result = js(SCROLL_JS) or {}
            scroll_passes += 1
            if scroll_result.get("at_bottom"):
                stopped_reason = "scroll_bottom"
                break
            time.sleep(scroll_pause_sec)

        kept: list[dict[str, Any]] = []
        for item in seen.values():
            age = parse_relative_age_days(str(item.get("ts") or ""))
            if age is not None and age > cutoff_days:
                continue
            profiles = [
                p
                for p in (
                    _normalize_profile_url(str(link))
                    for link in item.get("links") or []
                )
                if p
            ]
            item["profile_urls"] = list(dict.fromkeys(profiles))
            kept.append(item)

        lines = [f"[{m.get('ts', '')}] {m.get('text', '')}" for m in kept]
        markdown = "\n\n".join(lines)
        by_id = {str(m["id"]): m for m in kept if m.get("id")}

        return {
            "markdown": markdown,
            "items": kept,
            "messages": kept,
            "links": _dedupe_links(by_id),
            "stats": {
                "scroll_passes": scroll_passes,
                "unique_items": len(kept),
                "unique_messages": len(kept),
                "stopped_reason": stopped_reason,
                "lookback_days": lookback_days,
                "max_scrolls": max_scrolls,
            },
        }


def _is_login_href(href: str) -> bool:
    return bool(
        href and ("/login" in href or "/checkpoint" in href or "/uas/" in href)
    )


def _login_wall_payload(
    *,
    href: str,
    resume_url: str,
    rationale: str,
    allow_login_resume: bool,
) -> dict[str, Any]:
    if allow_login_resume:
        return {
            "status": "awaiting_credentials",
            "url": href,
            "name": "",
            "headline": "",
            "about": "",
            "markdown": "",
            "login": {
                "site": "linkedin.com",
                "url": href,
                "rationale": rationale,
                "fields": ["username", "password"],
            },
            "checkpoint": {"step": "post_nav", "resume_url": resume_url},
            "stats": {"stopped_reason": "login_required", "url": href},
        }
    return {
        "status": "login_required",
        "url": href,
        "name": "",
        "headline": "",
        "about": "",
        "markdown": "",
        "stats": {"stopped_reason": "login_required", "url": href},
    }


def _normalize_profile_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    m = _PROFILE_PATH_RE.search(raw)
    if not m:
        return None
    return m.group(0).rstrip("/")


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", folded.lower())


def name_matches(query: str, candidate: str) -> bool:
    """Every token of ``query`` appears in ``candidate`` (order-free)."""
    want = _tokens(query)
    have = set(_tokens(candidate))
    return bool(want) and all(t in have for t in want)


def _pick_search_match(
    query: str, candidates: list[dict[str, Any]], hint: str
) -> tuple[str | None, str, list[dict[str, Any]]]:
    """Return (url, stopped_reason, matching candidates).

    Only a single name match (after optional ``hint`` filter) is accepted —
    common names return ``ambiguous_match`` instead of guessing.
    """
    named = [
        c for c in candidates if name_matches(query, str(c.get("name") or ""))
    ]
    if hint:
        named = [
            c for c in named if name_matches(hint, str(c.get("snippet") or ""))
        ]
    if not named:
        return None, "no_search_match", []
    if len(named) > 1:
        return None, "ambiguous_match", named
    url = _normalize_profile_url(str(named[0].get("url") or ""))
    if not url:
        return None, "no_search_match", []
    return url, "ok", named


def enrich_profile(
    name: str | None = None,
    url: str | None = None,
    *,
    hint: str | None = None,
    boot_wait_sec: float = 3.0,
    allow_login_resume: bool = False,
) -> dict[str, Any]:
    """Open a LinkedIn profile (by URL, or a unique people-search match) and extract fields.

    Deterministic, no LLM. Failure modes (``status`` / ``stats.stopped_reason``):

    - ``missing_args`` — neither ``name`` nor ``url``
    - ``invalid_url`` — ``url`` given but not a ``/in/`` profile path
    - ``login_required`` / ``awaiting_credentials`` — auth wall
    - ``no_search_match`` — no search result whose name matches ``name``
    - ``ambiguous_match`` — several results match; ``stats.candidates`` lists them
    - ``name_mismatch`` — opened profile's name does not match ``name``
    - ``empty_profile`` — profile opened but name/headline/about all empty

    ``url`` is the reliable path. Name-only search accepts a result only when
    exactly one candidate's name contains every token of ``name`` (and of
    ``hint``, e.g. a company, when given).
    """
    profile_url = _normalize_profile_url(url or "")
    query = (name or "").strip()
    hint_text = (hint or "").strip()
    if not profile_url and not query:
        return {
            "status": "error",
            "url": "",
            "name": "",
            "headline": "",
            "about": "",
            "markdown": "",
            "stats": {"stopped_reason": "missing_args"},
        }
    if url and not profile_url and not query:
        return {
            "status": "error",
            "url": url or "",
            "name": "",
            "headline": "",
            "about": "",
            "markdown": "",
            "stats": {"stopped_reason": "invalid_url"},
        }

    if not profile_url:
        search_url = SEARCH_PEOPLE_URL.format(keywords=quote_plus(query))
        with tab(search_url):
            wait_for_load()
            time.sleep(boot_wait_sec)
            href = js("location.href") or ""
            if isinstance(href, str) and _is_login_href(href):
                return _login_wall_payload(
                    href=href,
                    resume_url=search_url,
                    rationale="LinkedIn enrich search hit login wall",
                    allow_login_resume=allow_login_resume,
                )
            raw_candidates = js(SEARCH_CANDIDATES_JS) or []
            if not isinstance(raw_candidates, list):
                raw_candidates = []
            candidates = [c for c in raw_candidates if isinstance(c, dict)]
            picked, reason, matched = _pick_search_match(
                query, candidates, hint_text
            )
            if not picked:
                shown = matched if reason == "ambiguous_match" else candidates
                return {
                    "status": "error",
                    "url": href if isinstance(href, str) else search_url,
                    "name": query,
                    "headline": "",
                    "about": "",
                    "markdown": "",
                    "stats": {
                        "stopped_reason": reason,
                        "candidates": [
                            {
                                "url": str(c.get("url") or ""),
                                "name": str(c.get("name") or ""),
                                "snippet": str(c.get("snippet") or "")[:160],
                            }
                            for c in shown[:5]
                        ],
                    },
                }
            profile_url = picked

    with tab(profile_url):
        wait_for_load()
        time.sleep(boot_wait_sec)
        href = js("location.href") or ""
        if isinstance(href, str) and _is_login_href(href):
            return _login_wall_payload(
                href=href,
                resume_url=profile_url,
                rationale="LinkedIn enrich profile hit login wall",
                allow_login_resume=allow_login_resume,
            )
        raw = js(PROFILE_EXTRACT_JS) or {}
        if not isinstance(raw, dict):
            raw = {}
        out_name = str(raw.get("name") or query or "")
        headline = str(raw.get("headline") or "")
        about = str(raw.get("about") or "")
        location = str(raw.get("location") or "") or None
        experience = str(raw.get("experience_snip") or "") or None
        final_url = str(raw.get("url") or href or profile_url)
        if not out_name and not headline and not about:
            return {
                "status": "error",
                "url": final_url,
                "name": query,
                "headline": "",
                "about": "",
                "markdown": "",
                "stats": {"stopped_reason": "empty_profile"},
            }
        found_name = str(raw.get("name") or "")
        if query and not name_matches(query, found_name):
            return {
                "status": "error",
                "url": final_url,
                "name": query,
                "headline": "",
                "about": "",
                "markdown": "",
                "stats": {
                    "stopped_reason": "name_mismatch",
                    "found_name": found_name,
                },
            }
        lines = [
            f"# {out_name}" if out_name else "# Profile",
            headline,
            f"Location: {location}" if location else "",
            about,
            f"Experience: {experience}" if experience else "",
        ]
        markdown = "\n\n".join(line for line in lines if line)
        result: dict[str, Any] = {
            "status": "ok",
            "url": final_url,
            "name": out_name,
            "headline": headline,
            "about": about,
            "markdown": markdown,
            "stats": {"stopped_reason": "ok"},
        }
        if location:
            result["location"] = location
        if experience:
            result["experience_snip"] = experience
        return result
