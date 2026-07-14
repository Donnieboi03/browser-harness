"""LinkedIn notifications scrape via logged-in Chrome."""
from __future__ import annotations

import re
import time
from typing import Any

from browser_harness.helpers import (
    finish_page,
    js,
    open_page,
    wait_for_load,
)

DEFAULT_NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"

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
) -> dict[str, Any]:
    """Open LinkedIn notifications, scroll, return markdown + links.

    Same return contract as ``slack.scrape_slack_channel`` so Virgil
    ``browser_source`` can consume it unchanged.
    """
    lookback_days = max(1, min(int(lookback_days), 30))
    max_scrolls = max(1, min(int(max_scrolls), 40))
    cutoff_days = float(lookback_days)

    open_page(url)
    wait_for_load()
    time.sleep(boot_wait_sec)

    # Login wall — stop cleanly; caller / human must sign in on scout Chrome.
    href = js("location.href") or ""
    if isinstance(href, str) and ("/login" in href or "/checkpoint" in href or "/uas/" in href):
        finish_page()
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
            # Enough cards past lookback — stop scrolling further back.
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

    # Filter to lookback when age is known; keep unknown-age items.
    kept: list[dict[str, Any]] = []
    for item in seen.values():
        age = parse_relative_age_days(str(item.get("ts") or ""))
        if age is not None and age > cutoff_days:
            continue
        kept.append(item)

    lines = [f"[{m.get('ts', '')}] {m.get('text', '')}" for m in kept]
    markdown = "\n\n".join(lines)
    by_id = {str(m["id"]): m for m in kept if m.get("id")}

    finish_page()

    return {
        "markdown": markdown,
        "items": kept,
        "messages": kept,  # alias for slack-shaped consumers
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
