"""Fetch page content as markdown via crawl4ai on the current browser tab."""
from __future__ import annotations

import time
from typing import Any

from browser_harness.helpers import (
    close_tab,
    crawl4ai_from_current_tab,
    ensure_real_tab,
    new_tab,
    page_info,
    wait_for_load,
)


def fetch_page_markdown(url: str, *, settle_sec: float = 2.0) -> dict[str, Any]:
    """Open URL, return fit/raw markdown and page metadata."""
    new_tab(url)
    wait_for_load()
    time.sleep(settle_sec)
    info = page_info()
    result = crawl4ai_from_current_tab()
    md = result.get("fit_markdown") or result.get("raw_markdown") or ""
    payload = {
        "markdown": md,
        "url": info.get("url") or url,
        "title": info.get("title") or "",
    }
    try:
        close_tab()
    except Exception:
        pass
    ensure_real_tab()
    return payload
