# Job application prefill

Use `browser-harness apply-job` — prefill-only by default (no Submit unless `--submit`).

## CLI

```bash
browser-harness apply-job \
  --url "https://job-boards.greenhouse.io/example/jobs/123" \
  --profile /path/to/profile.json
```

Never pass `--submit` unless the human explicitly approved submission.

## Profile schema

See `profile.example.json` in this folder.

## ATS support (v1)

| Host | Behavior |
|------|----------|
| greenhouse.io | Click Apply, fill standard fields, upload resume |
| myworkdayjobs.com | Page 1 fill only |
| ashbyhq.com | Single-page fill |
| smartrecruiters.com | Basic fill |
| linkedin.com | Visible fields only; never auto-submit |
| default | Generic email/name/resume heuristics |

## Blocked states

Returns JSON with `status: blocked` and `screenshot_path` on login walls or captcha.

## Virgil hook

Hermes skill `job-apply-browser` invokes this CLI via terminal — not Virgil Python.
