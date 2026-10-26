# Guide for the team

Your company works with **department assistants**: AI colleagues for Tech,
Sales, Finance and so on. You reach them in two places:

- **Matrix** (the chat app): talk to your department's assistant in your
  department's room, like you would with a colleague.
- **Team Portal** (this website): the work board, drafts waiting for your
  review, and your profile.

This page is also in the Portal under **Help**, and it grows as new things
arrive (see [What's new](#whats-new) at the end).

[TOC]

## Getting started

You need three things, which the person who set up your account gives you:
your **Matrix ID** (`@name:{{HOST}}`), an **initial password**, and access
to the company network (**Tailscale**, an app on your phone or laptop that
must be switched on).

1. **Install Tailscale** and sign in as instructed; leave it on.
2. **Install a Matrix app**: *Element X* (iPhone, Android) or *Element*
   (desktop), or use Element in the browser at `https://{{HOST}}:8443`.
3. **Sign in to the app**: choose "other server" / change the homeserver to
   `{{HOST}}`, then your user name (the part of your Matrix ID before the
   colon) and the initial password.
4. **Accept the invitations**: you are invited to your departments' rooms
   (and a direct message from **Portal**, which delivers your Portal login
   links). Until you accept, you are not in the room and the assistant cannot
   see what you write.
5. **Sign in to the Portal** at `https://{{HOST}}:10000` with your Matrix ID.
   A login link arrives as a direct message from Portal; open it within 10
   minutes. On another device than the one that asked, the Portal asks you to
   confirm first.
6. **Change your password** in the Portal: **Profile › Change password**
   (the mobile apps cannot do it). Your signed-in apps stay signed in.

## Matrix: working with your assistant

Open your department's room (for example **Tech**) and write normally:

- "What's on our board?"
- "Create a card: prepare the Q3 supplier comparison, due Friday."
- "Research the three biggest competitors of … and summarise in a table."
- "Draft a reply to this customer question: …"

**Each new message in the room starts a thread**, and the assistant answers
inside it. To continue the same conversation (answer its question, add a
detail, send the file it asked for), **reply in that thread**; a new message
in the room starts a fresh conversation that does not know the earlier one.
Everyone in the room can read every thread.
It answers only people listed for that department; people from other
departments cannot use your room's assistant.

### What the assistant can do

| Tool | What it means for you |
|---|---|
| Kanban board | Reads, creates and comments on your department's cards; moves work along and hands drafts to you for review |
| Web search and reading | Looks things up and reads web pages, with sources |
| Memory | Remembers lasting preferences and facts you ask it to remember ("always answer in German") |
| Skills | Reusable procedures it has learned for your department |
| Clarifying questions | Asks you when a request is ambiguous instead of guessing |
| To-do planning | Breaks larger requests into steps and works through them |
| Images, voice (preview) | Can create an image or an audio version of a reply when you ask |
| Company knowledge (Tech, preview) | Looks up and records structured company records (organisations, contacts, projects) |

It **cannot** run programs, open files on the server or reach other
departments' boards. Anything it produces for a decision goes to the
Portal's **Artifacts** for a human to approve.

### Slash commands

Type these as a message on their own. Your account may run:

| Command | What it does |
|---|---|
| `/help` | Lists the commands you can use |
| `/whoami` | Shows your access level and your commands |
| `/new` | Starts a fresh conversation in this thread (forgets its context; asks to confirm) |
| `/retry` | Sends your last message again |
| `/undo` | Takes back your last message and the answer to it |
| `/stop` | Stops what the assistant is doing right now |
| `/btw <question>` | A quick side question without derailing the current task |
| `/queue <message>` | Queues a message for after the current task |
| `/steer <message>` | Corrects the current task without stopping it |
| `/title <name>` | Names the conversation |
| `/status` | Shows the conversation's state (model, how full the context is) |
| `/compress` | Shortens a long conversation so the assistant stays sharp |

Other commands (changing the model, restarting, updates) are for the
operators; the assistant says so if you try one.

### Tips

- One request per message works best; say what "done" looks like.
- To send a file with a request, attach it and write the request as the
  file's caption, or send the file inside the thread.
- While it works you see short status lines (for example "kanban_list…").
  Writing again while it works corrects the running task.
- If nothing comes back within a minute, check that you joined the room
  (not just invited) and that Tailscale is on, then `/retry`.
- Right after someone's access changed, the assistants restart for a few
  seconds; a message sent in exactly that moment may need a `/retry`.

## HR: recruiting with the assistant

In the **HR** room the assistant keeps the recruiting records: open roles,
candidates with their CVs, and where each application stands. People
decide; the assistant prepares and records.

| You say | What happens |
|---|---|
| "Open a role from this JD" (with the file) | Creates the role with checkable must-haves; points out wording that could discriminate ("young team", "native speaker") |
| "Add Erika Testfrau to the backend role" (with CV and certificates) | Records the candidate, stores the documents, creates the application at stage *new* |
| "All applications for the backend role are in this ZIP" (then the ZIP in the thread) | Sorts the documents by person, shows you the plan, and after your yes adds every candidate with their documents. One ZIP is for one role: letters for another role are set aside for you to send separately |
| "Shortlist the top 5 for the backend role" | Compares candidates on the role's criteria, on CVs with names and personal details hidden; the shortlist arrives in the Portal under **Artifacts** for review |
| "Interview 1 with Erika done: …", "second round", "decision pending" | Moves the application along: new → reviewed → interviewed → decision → (another round) → hired / declined |
| "Decline Max, reason: no Kubernetes experience" | Asks you to confirm, then records the decision with your name |
| "Where are we with the backend role?" | Overview by stage, with what is waiting |
| "Delete everything about Lena" | Deletes the candidate with all applications and documents, after you confirm |

Good to know:

- Send CVs as **PDF, DOCX or text**, singly or as a **ZIP** (up to 25 MB and
  200 documents), on the same day (uploads are cleared after 24 hours).
  Photos are not stored.
- The assistant never records birth date, age, photo, gender, nationality,
  family, religion or health, and does not rank by them.
- Candidate records are **deleted automatically 6 months** after the last
  activity on them.
- Hiring decisions are yours: the assistant will not decide or decline in
  bulk for you.
- Onboarding and offboarding checklists exist as **drafts**: ask for them,
  but they do not keep records yet.

## Team Portal

### Dashboard (your landing page)

The Portal opens on your team's dashboard. Pick another team at the top if
you belong to several; leadership sees a tile per team first.

- **Objectives** for the period (quarter) with their **key results**: the
  current value against the target, a progress bar and a status: *on track*,
  *at risk* or *off track* against where the quarter line is today, *done*
  at 100 %.
- **KPIs**: the numbers the team watches continuously, with a trend line and
  a colour: green within target, amber past the warning threshold, red past
  the critical one. Board KPIs (cards completed, cycle time, cards in review)
  and HR KPIs (open roles, pipeline size, time to hire: counts only, never a
  person) are measured automatically every hour when something changed and
  every morning at 06:00.
- **Work**: cards awaiting your approval, blocked, in progress and done this
  week. Click one to open it.
- **Weekly reviews**: the team assistant's approved review of the week.

**Checking in.** Every team member can record the current value of a key
result or KPI: *check in* next to it, enter the number and, if you like,
what moved it. It is stored under your name with the date; the status
follows within the hour.

**Defining (team owners, i.e. people with approval rights for the team).**
*New objective* and *New KPI* at the top, *add key result* and *edit* on
each item. Keep key results measurable: a number with a start, a target and
a direction. **Measured by** decides who fills the value:

| Measured by | Who | `Metric` |
|---|---|---|
| manual | people, through check-ins | – |
| board | the Kanban board, automatically | `board.throughput window=7d`, `board.created`, `board.open`, `board.blocked`, `board.in_review`, `board.failures`, `board.cycle_time_p50_h`, `board.review_turnaround_p50_h` |
| records | the team's records (HR for now), automatically, counts only | `hr.open_roles`, `hr.candidates`, `hr.applications stage=interviewed`, `hr.hired window=30d`, `hr.time_to_hire_p50_d` |
| agent | the team assistant from a registered source (coming) | – |

*Delete* removes an objective with its key results and their history; the
records keep who deleted what and when. You can also ask the team assistant
in chat ("how are we doing on the objectives?", "check in: leads = 42").

### The board

Columns follow the work: **Triage** (new ideas the assistant will shape),
**Todo / Ready** (waiting), **In Progress** (someone is on it), **Review**
(a draft waits for a decision), **Blocked**, **Done**.

- **+** on a column creates a card. Pick the department assistant as
  assignee if it should do the work; it picks the card up within a minute.
- Drag cards between columns. Some moves are not allowed (only reviewers
  complete a card or move it out of Review); the Portal says why.
- Click a card for details, comments and attached files (up to 25 MB).
- **Stakeholders** on a card: an *owner* (accountable), *reviewers* and
  *watchers*. Anyone in the team can follow a card as a watcher; people
  with approval rights name owners and reviewers. When a card names
  reviewers, only they can approve it. A card can *serve a key result*
  (pick one when you create it, or on the owner's entry): the dashboard
  then lists it under that key result.
- **The card's thread in chat.** When a card is created, the team's
  assistant posts it in the team room; what happens to it afterwards (done,
  blocked, comments, moves, reviews) lands in that thread, naming the
  stakeholders so they are notified. Reply in the thread to talk to the
  assistant about the card. *Open the card's thread in chat* on the card.

You see your own departments' cards only (leadership sees all).

### Reviewing drafts (Artifacts)

**Artifacts** lists the cards waiting in Review that you may see.

- Open the attachment (PDFs, images and plain text preview in the browser;
  other files download).
- **Approve** completes the card; your name is recorded with the approval.
- **Request changes**: say concretely what should change. The card goes
  back to the assistant, which reworks it and hands it back.
- The badge shows how long is left. Cards with an autonomy level say what
  happens at the deadline: "needs your decision" (never decided for you) or
  "auto-approves in N h unless you object". Without a level, your
  department's default applies after 48 h.

Only people with review rights for a department see Approve and Request
changes there.

### Profile

Your name, Matrix ID, departments and where you may approve; **Change
password** for your Matrix password; **Log out**.

### People (owners only)

If you manage your team's access, **People** lists everyone on your server.

- **Add person**: name, user name (becomes `@name:{{HOST}}`), and per
  department whether they are a member and whether they may approve. The
  Portal shows the sign-in details once, with **Copy** buttons and **Copy
  all**; hand them over in person or by phone, not by e-mail.
- **Change**: tick or untick departments. New rooms are offered at once;
  rooms they no longer belong to are left for them.
- **Remove person**: takes away every room and the Portal; the account is
  closed for good.

Each change takes up to a minute. You can only hand out departments you can
see and approval where you may approve; owners and your own account are
changed by the operator. Invite people only here, not from the Matrix app:
invitations made in the app are withdrawn again.

## Good to know

- Do not paste passwords, card numbers or other people's personal data
  into cards or chats unless your team's process says so.
- Everything stays on your company's server and network; the assistants
  use an external AI model to think, so treat chats like e-mail to a
  colleague, not like a diary.
- Something wrong or missing? Tell the person who set up your account.

## What's new

- **2026-10-26 (afternoon)**: the **Dashboard** is the Portal's landing page: your team's objectives, key results, KPIs with trends, open work and weekly reviews. Team owners define them there; everyone checks in values.
- **2026-10-26 (evening)**: cards have **stakeholders** (owner, reviewers, watchers), can **serve a key result**, and get **a thread in the team room** where their events and your comments land.
- **2026-10-26**: text you enter in the Portal is checked for hidden
  (invisible) characters, which can carry instructions for a bot that nobody
  sees; they are removed and the Portal tells you. Department digests now
  end with the bot's spend over the last 7 days.
- **2026-10-25 (evening)**: HR takes a ZIP of applications for one role at
  once.
- **2026-10-25 (afternoon)**: the **HR** room with recruiting support (roles,
  candidates and CVs, shortlists, interview stages); how threads work in
  Matrix.
- **2026-10-25**: this guide in the Portal (**Help**); change your password
  in the Portal; Copy buttons for new accounts; owners manage people in the
  Portal; slash commands for everyone (see above).
- **2026-10-24**: Matrix rooms per department, Portal login via Matrix,
  phone access over HTTPS, morning digests in the department rooms.
