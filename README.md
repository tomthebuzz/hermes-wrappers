# FutureTree Team Portal

Standalone web app giving the wider team (non-developers) scoped access to
Kanban board status and Artifact review — nothing else. Deliberately NOT a
Hermes dashboard plugin: the dashboard's plugin HTTP routes are
unauthenticated by design (confirmed in Hermes Kanban docs — the dashboard's
auth middleware explicitly skips `/api/plugins/*`, assuming localhost-only
binding). This app can't inherit that assumption since it's meant to be
reachable by 8-12 external people and eventually a public domain
(futuretree.com), so it does its own auth and its own RBAC from scratch.

## IMPORTANT — built blind, verify before trusting

Written in a sandbox with no live Hermes install, no real kanban.db, and no
way to run an end-to-end test against actual data. Syntax-checked, not
integration-tested. Treat as a strong skeleton to validate on the real host,
not a finished product.

## Architecture

- **Reads** go straight against `~/.hermes/kanban.db` (SQLite, WAL mode —
  safe for concurrent external readers per the Hermes docs: "WAL mode means
  the read loop never blocks the dispatcher's BEGIN IMMEDIATE claim
  transactions").
- **Writes** (create task, claim/assign, comment, approve/reject an
  artifact) shell out to the `hermes kanban` CLI rather than touching SQLite
  directly — this guarantees we never bypass kanban_db's invariants (status
  transitions, task_events logging, dispatcher notifications). Slower than
  a raw INSERT, correctness matters more here.
- **Auth** is pluggable, two backends:
  - `magic_link_telegram` (default now): `/login` asks for the person's
    Telegram username/ID, the portal calls `hermes send telegram` (or the
    person's known chat_id) to DM a one-time token, they click the link.
    No domain/widget dependency — works today on the tailnet.
  - `telegram_login_widget` (switch to this once futuretree.com is live):
    standard Telegram Login Widget flow, needs `/setdomain` in BotFather
    pointed at the real domain first.
- **RBAC**: a small `users.yaml` (see `app/rbac.py`) maps
  `telegram_user_id -> {name, role, tenants: [...], can_rollup: bool}`.
  This is the ONE place that decides who sees what — the actual enforcement
  point missing from raw Hermes/Kanban.

## Layout

```
team-portal/
  app/
    main.py              FastAPI app, routes, auth gate on every request
    rbac.py               users.yaml loader + per-request scoping decisions
    kanban_read.py        read-only SQLite queries against kanban.db
    kanban_write.py        shells out to `hermes kanban ...` for writes
    auth/
      magic_link.py        Telegram-DM one-time-token login
      telegram_widget.py   stub for the prod login widget flow
    artifacts/
      sla.py               deadline helpers shared with the cron sweep repo
    static/                minimal UI (to flesh out in Phase 1/2)
  docker/
    Dockerfile
    docker-compose.yml
  users.yaml.example
  requirements.txt
  README.md (this file)
```

## Phase mapping

- Phase 1 (this skeleton): Kanban read view, tenant-scoped + rollup, create/
  claim/assign via CLI shellout, magic-link auth, `users.yaml` RBAC.
- Phase 2 (done): Artifact publish/review endpoints (approve/reject/
  comment), review-queue listing with SLA countdown, shared SLA-deadline
  convention with the sibling `hermes-team-bots` cron sweep via
  `config/sla-defaults.yaml` + `config/tenants.yaml` (kept in sync by hand
  across the two repos for now — see infra/README.md for the K8s-level fix
  once both are deployed together). Minimal vanilla-JS static UI added at
  `app/static/index.html` — Kanban view + Artifact review queue with
  approve/reject/comment, no build step.
- Phase 3: no portal changes — that phase is the bot roster / Telegram
  wiring, lives entirely in the other repo.
- Phase 4: swap `auth_backend: telegram_login_widget` in config once
  futuretree.com + BotFather /setdomain are live; point `KANBAN_DB_PATH` /
  `HERMES_BIN` env vars at the production host.

## K8s deployment

See `infra/README.md` — Kustomize base under `infra/base/`, with real
unresolved decisions flagged there (kanban.db access pattern, image build,
ingress timing) rather than silently assumed.

## Validation checklist (run on the real machine)

1. `cp users.yaml.example users.yaml` and fill in real Telegram user IDs +
   roles for your 8-12 people (plus the 2 devs if you want them in the
   portal too, though they have full dashboard access already).
2. `docker compose -f docker/docker-compose.yml up --build`
3. Point `KANBAN_DB_PATH` at the real `~/.hermes/kanban.db` (bind-mount it
   read-only into the container) and `HERMES_BIN` at a `hermes` binary the
   container can actually exec (likely needs the full Hermes install inside
   the image, or a thin RPC shim to the host — decide this before Phase 1
   sign-off, see the Dockerfile TODO).
4. Hit `/healthz`, then `/login`, then confirm a logged-in session only
   sees its own tenant(s) by comparing two different test users.
