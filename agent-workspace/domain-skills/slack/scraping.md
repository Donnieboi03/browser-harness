# Slack channel scraping

Use `browser_harness.domains.slack.scrape_slack_channel` (or Virgil `invoke_domain("slack.scrape_slack_channel", ...)`).

## Why not crawl4ai / window.scrollBy

Slack is a virtualized React app. Messages live in `.c-scrollbar__hider` panes; `window.scrollBy` does not load history. crawl4ai returns accessibility shell text, not message bodies.

## Procedure

1. `new_tab(channel_url)` — user must be logged into Slack in Chrome.
2. Wait ~5s for channel boot.
3. Each pass: extract `[data-qa="message_container"]`, scroll the largest `.c-scrollbar__hider` pane **up** 85% viewport.
4. Accumulate messages by archive-link id (virtualized DOM reuses nodes).
5. Stop when:
   - Oldest message `ts_unix` from `/archives/.../p{ts}` is older than `lookback_days`
   - Pane `scrollTop` hits 0
   - `lookback_days * scrolls_per_day` passes exhausted
6. `close_tab()` + `ensure_real_tab()` when done.

## Defaults

- `lookback_days=14`, `scrolls_per_day=2` → up to 28 scroll passes
- Returns `{markdown, messages, links, stats}`

## Timestamp parsing

Archive href `.../p1781321112539969` → `1781321112.539969` Unix seconds (last 6 digits = microseconds).
