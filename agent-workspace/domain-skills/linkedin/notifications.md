# LinkedIn — Notifications digest

Read-only scrape of `https://www.linkedin.com/notifications/` for Virgil
briefing jobs (`linkedin.scrape_notifications`).

## Domain API

```python
from browser_harness.domains.linkedin import scrape_notifications

result = scrape_notifications(
    url="https://www.linkedin.com/notifications/",
    lookback_days=3,
    max_scrolls=15,
)
# result["markdown"], result["links"], result["stats"], result["items"]
```

Virgil job: `config/schedules.yaml` → `linkedin_digest_morning` with
`chrome_profile: scout` (CDP **9223**).

## Prerequisites

- LinkedIn session on **scout** Chrome (`~/.chrome-virgil/scout`), not everyday.
- Account: the operator's own LinkedIn login (never committed).
- First nav: `new_tab` — domain handles open/close + `ensure_real_tab`.

## Behavior

1. Opens notifications URL.
2. If redirected to login/checkpoint → returns `stopped_reason=login_required`
   (empty markdown). Do not type passwords.
3. Extracts card text + http(s) links; scrolls the window until lookback,
   bottom, or `max_scrolls`.
4. Relative times (`2d`, `3h`, `Yesterday`) filter older cards when present.

## Safety

- **Read-only.** Do not Accept/Ignore invites here — see `invitation-manager.md`.
- Close tabs after scrape (domain does this).
- Delete any debug screenshots you take.

## Virgil wiring

```bash
export BU_NAME=virgil-scout BU_CDP_URL=http://127.0.0.1:9223
# or: python scripts/run_briefing_job.py linkedin_digest_morning --dry-run
# (applies chrome_profile from schedules.yaml automatically)
```
