# WO-005 — remove dashboard authentication entirely

**From:** CW, at the Operator's direction · **Date:** 2026-09-05
**Type:** build. This is a decision, not a defect.

The Operator chose a fully open dashboard — no token, no login, every route
including `POST /api/run`. He was offered read-open / spend-gated and declined
it. Finding 004 is **superseded**. After this ships, an unauthenticated
dashboard is the intended posture. Do not "fix" it. If the system stops being
a single-user instrument, put the decision back in front of the Operator.

## What shipped

- `DASHBOARD_AUTH=off` by default. Any other value turns the token gate back on.
- Lock page copy removed. Auth-on returns a plain 401.
- `DASHBOARD_TOKEN` stays in the Blueprint with `sync: false` and no
  `generateValue` / no `value: ""`.
- `MAX_RUNS_PER_DAY` (default 5) counted from `runs`. Refusal is logged.
- Per-IP cooldown on `POST /api/run` (`RUN_COOLDOWN_SECONDS`, default 600).
- Provider billing bodies and `request_id` values stay off rendered pages;
  full text goes to logs.
- `RUN_BUDGET_USD` unchanged.

## Cookie vs query (WO-005 §4)

Confirmed in source. `_provided_token` used `Authorization or cookie or query`.
A stale `access_token` cookie short-circuited a correct `?token=`. That is why
a cookie-free client got 200 and the Operator's browser got the lock page from
the same URL. Query now wins over cookie. Auth-off deletes any leftover cookie.
