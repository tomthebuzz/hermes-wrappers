# Team Portal

**Deploying all three repos together? See
[hermes-bridge/RUNBOOK.md](https://github.com/tomthebuzz/hermes-bridge/blob/main/RUNBOOK.md)
for the full step-by-step order — this README covers this repo's own
internals.**

Standalone web app giving the wider team (non-developers) scoped access to
Kanban board status and Artifact review — nothing else. Deliberately NOT a
Hermes dashboard plugin: the dashboard's plugin HTTP routes are
unauthenticated by design (confirmed in Hermes Kanban docs — the dashboard's
auth middleware explicitly skips `/api/plugins/*`, assuming localhost-only
binding). This app can't inherit that assumption since it's meant to be
reachable by 8-12 external people and eventually a public domain
(team-portal.example.com), so it does its own auth and its own RBAC from scratch.

## Current portal features

- Header navigation: **Kanban**, **Artifacts**, **Profile**, and **Log out**.
- Profile shows account, Telegram username, immutable numeric Telegram user ID/chat ID, role, and tenant scope. Users can update their username; numeric Telegram IDs are identity/security credentials and remain administrator-managed in `users.yaml` (changing them without verifying the new Telegram account could transfer access).
- Kanban is a column board for triage, todo, ready, running, review, blocked, done, and archived. Filters include team, assignee / My Items, due-date bucket (overdue, this week, this month, later, no date), and priority. Each column has a **+** action to create a card assigned to the active portal user.
- Drag/drop is state-aware: review cards are reopened through Hermes before an implementation claim, and running tasks use Hermes `reclaim` when moved back to Ready. Invalid/dependency-blocked transitions produce actionable messages; no raw status SQL updates.
- Click a card to edit its title, body, priority, assignee, and comments within tenant scope. Artifact cards offer upload and authorized review actions.
- Uploads are capped at 25 MB and stored through `hermes kanban attach`; the portal mounts the host attachment directory read-only for authorized access. PDF/image/text files open inline, with a separate Download link; other file types download.
- Three clearly marked demo artifacts can be seeded through the bridge with `python3 scripts/seed_demo_artifacts.py --confirm`. They are created in the existing `marketing` tenant (no extra demo tenant), and are genuine review-lane tasks, so authorized users can comment, approve, or request changes. The script repairs partial demo tasks that aren't yet in `review`. Remove them with `hermes kanban archive <id>` after testing.

## Hermes Bridge (write path)

Kanban writes (create/claim/assign/comment/approve/reject/publish-for-
review) and the magic-link Telegram send both go through
**[hermes-bridge](../hermes-bridge)** when `HERMES_BRIDGE_URL` is set —
the standalone service that runs natively next to the real Hermes install
and execs the `hermes` CLI on this app's behalf, so this container never
needs Hermes installed in it. See that repo's README for why this exists
and how to run it. Without `HERMES_BRIDGE_URL` set, this app falls back to
shelling out to a local `hermes` binary directly (useful for native/dev
runs where this process IS on the Hermes host) — same code, two modes.

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
  artifact) go through `hermes-bridge` when `HERMES_BRIDGE_URL` is set;
  the bridge runs next to the real Hermes install and calls `hermes kanban`
  / `hermes send telegram`. Direct local CLI fallback remains for native
  dev runs only. This keeps containers free of any Hermes install while
  preserving kanban_db's write invariants.
- **Auth** is pluggable, two backends:
  - `magic_link_telegram` (default now): `/login` asks for the person's
    Telegram `@username`; `users.yaml` resolves that to a numeric
    `telegram_user_id` (session identity) and `telegram_chat_id` (delivery
    target, usually the same number). Numeric login still works for recovery.
    Telegram bots generally cannot initiate arbitrary DMs by `@username`, so
    delivery should stay numeric even though the UI is handle-first.
  - `telegram_login_widget` (switch to this once team-portal.example.com is live):
    standard Telegram Login Widget flow, needs `/setdomain` in BotFather
    pointed at the real domain first.
- **RBAC**: a small `users.yaml` (see `app/rbac.py`) maps
  `telegram_username` / `telegram_user_id` to `{name, role, tenants,
  can_rollup, can_approve_artifacts}`. This is the ONE place that decides
  who sees what — the actual enforcement point missing from raw Hermes/Kanban.

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
    static/                column Kanban, filters, task/artifact modals, profile
  scripts/
    seed_demo_artifacts.py seeds 3 clearly-marked review cards via bridge
  docker/
    Dockerfile
    docker-compose.yml   # points at hermes-bridge via host.docker.internal
  users.yaml.example
  requirements.txt
  README.md (this file)
```

## Phase mapping

- Phase 1: tenant-scoped Kanban board, create/claim/assign via the bridge,
  @username magic-link auth, `users.yaml` RBAC.
- Phase 2 (done): Artifact publish/review endpoints (approve/reject/
  comment), review-queue listing with SLA countdown, shared SLA-deadline
  convention with the sibling `hermes-team-bots` cron sweep via
  `config/sla-defaults.yaml` + `config/tenants.yaml` (kept in sync by hand
  across the two repos for now — see infra/README.md for the K8s-level fix
  once both are deployed together). Minimal vanilla-JS static UI added at
  `app/static/index.html` — true column-based Kanban board + Artifact review
  queue with approve/reject/comment, no build step.
- Phase 3: no portal changes — that phase is the bot roster / Telegram
  wiring, lives entirely in the other repo.
- Phase 4: swap `auth_backend: telegram_login_widget` in config once
  team-portal.example.com + BotFather /setdomain are live; point `KANBAN_DB_PATH` /
  `HERMES_BIN` env vars at the production host.

## K8s deployment

See `infra/README.md` — Kustomize base under `infra/base/`, with real
unresolved decisions flagged there (kanban.db access pattern, image build,
ingress timing) rather than silently assumed.

## Validation checklist (run on the real machine)

1. `cp users.yaml.example users.yaml` and fill in real Telegram @usernames,
   numeric user IDs, chat IDs, roles, and tenant scopes for your 8-12 people
   (plus the 2 devs if you want them in the portal too, though they have
   full dashboard access already).
2. `docker compose -f docker/docker-compose.yml up --build`
3. Confirm the container has `KANBAN_DB_PATH=/data/kanban.db`,
   `HERMES_BRIDGE_URL=http://host.docker.internal:8765`, and the correct
   `HERMES_BRIDGE_API_KEY` (docker-compose.yml already wires these from env).
4. Hit `/healthz`, then `/login` with an @username, then confirm a logged-in
   session only sees its own tenant(s) by comparing two different test users.
   If no Telegram message arrives, the `/login` API now returns a 502 when the
   bridge reports a send failure; also check `/tmp/hermes-bridge.log` and make
   sure the user has started the Telegram bot at least once.
