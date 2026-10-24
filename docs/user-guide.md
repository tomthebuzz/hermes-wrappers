# Team Portal — guide for the team

The Team Portal shows your department's work board and the drafts the
department assistant (a Hermes agent) produces for you to check. Your
department also has a chat room where you can talk to the assistant directly.

## Sign in

1. Open the Portal link you were given and enter your chat ID — your Matrix
   ID (`@name:server`) or your Telegram `@username`.
2. A login link arrives as a direct message (from the Portal bot in Matrix, or
   the Telegram bot). It works once and for 10 minutes.
3. Open it in the same browser and you are in. If you open it on another
   device, the Portal asks you to confirm the account name first — only
   continue if it is yours and you asked for the link.

You only ever see your own department's cards (leadership sees all).

## The board

Columns follow the work: **Triage** (new ideas the assistant will shape),
**Todo / Ready** (waiting), **In Progress** (someone is on it), **Review**
(a draft waits for a decision), **Blocked**, **Done**.

- **+** on a column creates a card. Pick the department assistant as assignee
  if it should do the work; it picks the card up within about a minute.
- Drag cards between columns. Some moves are not allowed (for example, only
  reviewers can complete a card or move it out of Review); the Portal says why.
- Click a card for details, comments and attached files.

## Reviewing drafts

**Artifacts** lists the cards waiting in Review that you may see.

- Open the attachment (PDFs, images and plain text preview in the browser;
  other files download).
- **Approve** completes the card; your name is recorded with the approval.
- **Request changes**: say concretely what should change. The card goes back
  to the assistant, which reworks it and hands it back for review.
- The badge shows how long is left. Cards with an autonomy level say what
  happens at the deadline: "needs your decision" (never decided for you) or
  "auto-approves in N h unless you object". Without a level, your
  department's default applies after 48 h.

Only people with review rights for a department see the Approve and Request
changes buttons there.

## Your department room

In Element (or any Matrix app) open your department's room and write to the
assistant as you would to a colleague: "what's on our board?", "draft a
summary of …". It can read and create cards for your department and look
things up on the web; it cannot run programs or open files on the server.
When a card is ready for review or done, the assistant posts it in the room,
and each morning it posts a digest of the board.

## People (owners)

If you manage your team's access, **People** in the top bar lists everyone on
your server. You never need the server itself:

- **Add person**: name, user name (becomes `@name:server`), and per team
  whether they are a member and whether they may approve drafts. The Portal
  shows the initial password once; give it to the person yourself, not by
  e-mail. They sign in to Element or any Matrix app (homeserver = the server
  name, Tailscale on), accept the invites to their teams' rooms and change
  the password in Element Web (Settings › Account).
- **Change**: tick or untick teams. New rooms are offered at once; rooms
  they no longer belong to are left for them.
- **Remove person**: takes away every room and the Portal; the account is
  closed for good.

Each change takes up to a minute (the assistants restart to pick it up).
You can only hand out teams you can see and approval where you may approve;
owners and your own account are changed by the operator.

## Good to know

- Do not paste passwords, card numbers or other people's personal data into
  cards or chats unless your team's process says so.
- Anything the assistant produces is a draft until a person approves it.
- Problems? Tell the operator; the system checks itself every 30 minutes and
  alerts them when something breaks.
