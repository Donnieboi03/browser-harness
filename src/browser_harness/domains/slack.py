"""Slack channel scrape via logged-in Chrome (virtualized message pane)."""
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

_ARCHIVE_TS_RE = re.compile(r"/p(\d+)")

SCROLL_JS = """(() => {
  const hiders = [...document.querySelectorAll('.c-scrollbar__hider')]
    .filter(el => el.scrollHeight > el.clientHeight + 200)
    .sort((a, b) => b.scrollHeight - a.scrollHeight);
  const pane = hiders[0];
  if (!pane) return {ok: false, at_top: true};
  const before = pane.scrollTop;
  pane.scrollTop = Math.max(0, pane.scrollTop - pane.clientHeight * 0.85);
  return {ok: true, before, after: pane.scrollTop, at_top: pane.scrollTop <= 0};
})()"""

EXTRACT_JS = """(() => {
  const skip = (h) => /slack\\.com\\/(help|legal)|slack-status\\.com/.test(h);
  const parseTs = (href) => {
    const m = (href || '').match(/\\/p(\\d+)/);
    if (!m) return null;
    const raw = m[1];
    if (raw.length <= 6) return parseInt(raw, 10);
    const sec = parseInt(raw.slice(0, -6), 10);
    const micro = parseInt(raw.slice(-6), 10);
    return sec + micro / 1e6;
  };
  const out = [];
  for (const m of document.querySelectorAll('[data-qa="message_container"]')) {
    const anchor = m.querySelector('a[href*="/archives/"]');
    const id = anchor ? anchor.href : m.innerText.slice(0, 80);
    const ts_unix = anchor ? parseTs(anchor.href) : null;
    const textEl = m.querySelector('[data-qa="message-text"], .p-rich_text_section');
    const text = (textEl ? textEl.innerText : m.innerText).trim().replace(/\\s+/g, ' ');
    if (!text) continue;
    const tsEl = m.querySelector('[data-qa="timestamp"], .c-timestamp__label');
    const ts = tsEl ? tsEl.innerText.trim() : '';
    const links = [...m.querySelectorAll('a[href^="http"]')]
      .map(a => a.href)
      .filter(h => !skip(h) && !h.includes('slack.com/archives'));
    out.push({id, ts, ts_unix, text: text.slice(0, 800), links});
  }
  return out;
})()"""


def parse_slack_archive_ts(href: str) -> float | None:
    """Parse Slack archive link timestamp (``/p{seconds}{micros}``) to Unix seconds."""
    m = _ARCHIVE_TS_RE.search(href)
    if not m:
        return None
    raw = m.group(1)
    if len(raw) <= 6:
        return float(int(raw))
    sec = int(raw[:-6])
    micro = int(raw[-6:])
    return sec + micro / 1_000_000


def _dedupe_links(messages: dict[str, dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in messages.values():
        for link in item.get("links") or []:
            normalized = link.split("?")[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(link)
    return out


def scrape_slack_channel(
    url: str,
    *,
    lookback_days: int = 14,
    scrolls_per_day: int = 2,
    boot_wait_sec: float = 5.0,
    scroll_pause_sec: float = 0.9,
) -> dict[str, Any]:
    """Open Slack channel, scroll up through history, return messages and links.

    Stops when the oldest collected message is older than ``lookback_days``,
    the scroll pane hits the top, or ``lookback_days * scrolls_per_day`` passes.
    """
    lookback_days = max(1, min(lookback_days, 90))
    scrolls_per_day = max(1, min(scrolls_per_day, 10))
    max_passes = lookback_days * scrolls_per_day
    cutoff = time.time() - lookback_days * 86400

    open_page(url)
    wait_for_load()
    time.sleep(boot_wait_sec)

    seen: dict[str, dict[str, Any]] = {}
    stopped_reason = "max_passes"
    scroll_passes = 0

    for _ in range(max_passes):
        batch = js(EXTRACT_JS)
        for item in batch:
            seen[item["id"]] = item

        oldest_ts = min(
            (m["ts_unix"] for m in seen.values() if m.get("ts_unix")),
            default=None,
        )
        if oldest_ts is not None and oldest_ts < cutoff:
            stopped_reason = "lookback_reached"
            break

        scroll_result = js(SCROLL_JS)
        scroll_passes += 1
        if scroll_result.get("at_top"):
            stopped_reason = "scroll_top"
            break

        time.sleep(scroll_pause_sec)

    messages = list(seen.values())
    lines = [f"[{m.get('ts', '')}] {m.get('text', '')}" for m in messages]
    markdown = "\n\n".join(lines)

    finish_page()

    return {
        "markdown": markdown,
        "messages": messages,
        "links": _dedupe_links(seen),
        "stats": {
            "scroll_passes": scroll_passes,
            "unique_messages": len(messages),
            "stopped_reason": stopped_reason,
            "lookback_days": lookback_days,
            "scrolls_per_day": scrolls_per_day,
        },
    }
