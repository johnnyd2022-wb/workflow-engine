# Slack watcher setup

Lets you tag `@claude` at the top level of a Slack channel, have a short triage
conversation, and hand the result to the normal autonomous chain — from your phone.

The official Claude Slack app only answers tags **inside threads**. This fills the gap at
the top level, and deliberately does not compete with it.

## How it is put together

```
systemd timer (every 1 min)
  └─ scripts/slack_watch.py         ← plain HTTP, READ-ONLY token. Zero tokens.
       ├─ nothing new?  exit 0      ← the common case, costs nothing
       └─ new @claude mention:
            └─ claude -p /slack-watcher        ← intent routing (cheap model)
                 ├─ answer  → Xero / Gmail / Drive MCP, posts result as YOU
                 ├─ handoff → returns spec; script launches /fix-bug|/new-feature
                 ├─ ask     → posts a clarifying question
                 └─ decline → posts where it should go instead
```

**The script reads; the agent writes.** The token is read-only (`channels:history`), and
every reply is posted by the agent through your Slack MCP connector — so replies appear as
you rather than as a bot.

The trade-off, stated plainly: the agent now holds live Xero, Gmail, and Drive connections
while reading text anyone in the channel can write. Three things hold that line — the
destination channel and thread are pinned in the prompt *outside* the untrusted fence, the
allow-list excludes Bash, file writes, and every send-email tool, and
`.agents/autonomy.md` still bars external comms, merges, deploys, and production database
access regardless of what a thread says.

## Token cost

This is the part that decides whether the thing is affordable.

| Event | Frequency | Cost |
|---|---|---|
| Poll finding nothing | 1440×/day at 1 min | **0 tokens** — no model is invoked |
| One triage / answer turn | per human message | ~70k input, almost all cache reads |
| Handoff chain | per confirmed request | full `fix-bug` / `new-feature` run |

Two measurements taken on this machine:

- **~13k tokens** for a trivial `claude -p` in an empty directory — the floor for *any*
  headless invocation.
- **~72k cache-read tokens** for one run in this repo with the MCP connectors loaded.

That second number is the important one. It is the real cost of waking a model here, and it
is why the poll must never be one: polling via MCP every minute would be roughly
**100M tokens/day** to discover nothing happened.

Three things keep the triage end cheap:

- **`triage_model` is Haiku** in `.agents/slack-watch.json`. Triage is reading
  comprehension, not engineering.
- **Deterministic session IDs.** A thread always maps to the same session UUID
  (`uuid5` of `channel:thread_ts`), so follow-up turns use `--resume` and hit the prompt
  cache instead of rebuilding context.
- **The skill forbids investigation.** No repo greps, no `preflight`, no file reads during
  triage — `fix-bug` does that properly downstream.

Ballpark: a day with 3 real requests and 2 clarifying turns each is well under 200k input
tokens, nearly all cache reads. The handed-off chains dominate the bill, and those are work
you asked for.

## One-time setup

### 1. Slack app and token

The app already exists — `claude2` (`U0BKALN1A4F`) in the Whistlebird workspace, token in
KeePassXC at `workflow-engine/slack_bot_token`.

**It is missing one scope.** Verified live against Slack:

```
provided: commands, chat:write, app_mentions:read, channels:read
needed  : channels:history
```

At <https://api.slack.com/apps> → your app → **OAuth & Permissions** → Bot Token Scopes,
add:

| Scope | Why |
|---|---|
| `channels:history` | **required** — read public channel messages |
| `groups:history` | only if you watch a private channel |

Then **reinstall the app to the workspace**. New scopes do not apply to an already-issued
token; without the reinstall you will keep getting `missing_scope` with the same token.
Re-copy the `xoxb-` token into KeePassXC afterwards if it changes.

**`chat:write` is surplus now** and can be removed. The script never posts — the agent
replies through your Slack MCP connector, so replies appear as *you*, not as `claude2`.
Leaving it costs nothing but grants more than the design needs.

Finally, **invite the bot to the channel**: `/invite @claude2`. Without it,
`conversations.history` returns `not_in_channel`.

### 2. Store the token in KeePassXC

`.agents/notifications.json` says no bot token lives in this repo, and that still holds —
the token goes in KeePassXC alongside the other local secrets:

```bash
keepassxc-cli add -p /mnt/c/Users/OEM/Documents/workflow-engine/Passwords.kdbx \
  workflow-engine/slack_bot_token
```

Paste the `xoxb-` token as the password. `scripts/slack_watch.py` reads it through
`scripts/local_secrets.py`. `SLACK_BOT_TOKEN` in the environment overrides it, which is the
easier path for a first test.

> **Note on the unattended path:** KeePassXC needs `KEEPASS_PASSWORD` to open the database
> non-interactively. It is exported in `~/.bashrc`, which systemd does **not** source — so
> the timer unit reads it from `~/.config/slack-watch.env` instead. Without it a
> timer-driven run fails cleanly rather than hanging.

### 3. Point it at a channel

Edit `.agents/slack-watch.json`:

- `channels` — start with **one**. `#general` (`C04R93YLPMH`) is a reasonable intake.
  Keep `#code-changes` out of it: that channel is a notification surface, and making it an
  intake too is how it stops being readable.
- `claude_app_user_id` — **every** Claude identity in the workspace, as a list. Currently
  `["U0BGZ4YKJF3", "U0BKALN1A4F"]`: the official Claude app, and `claude2` (the bot this
  watcher authenticates as). Both are needed — typing `@claude` autocompletes to whichever
  Slack ranks first, and the rendered text is an opaque ID, so matching only one silently
  drops half the mentions. This cost an hour to find; don't trim it to one.
- `sensitive_data_channels` — see below. Empty by default, which is the safe setting.

### 4. Test before automating

```bash
export SLACK_BOT_TOKEN=xoxb-...

# post "@claude test" in the channel first, then:
python3 scripts/slack_watch.py --dry-run    # finds work, invokes nothing, posts nothing
python3 scripts/slack_watch.py              # real run: one triage turn
```

`--dry-run` is the safe way to confirm the bot can see the channel.

### 5. Run it on a timer

`~/.config/systemd/user/slack-watch.service`:

```ini
[Unit]
Description=Slack @claude watcher

[Service]
Type=oneshot
WorkingDirectory=/home/johnny/workflow-engine
EnvironmentFile=-/home/johnny/.config/slack-watch.env

# systemd's user PATH excludes ~/.local/bin, where `claude` lives. Without this,
# every triage dies with a bare ENOENT that nobody is awake to read.
Environment=PATH=/home/johnny/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin

# NOT /usr/bin/python3 — that is 3.10 on this box and the script needs 3.11+
# (datetime.UTC); pyproject requires >=3.14.
ExecStart=/home/johnny/.local/bin/python3 scripts/slack_watch.py
TimeoutStartSec=900
```

`~/.config/slack-watch.env` (chmod 600 — this file holds a password):

```
KEEPASS_PASSWORD=...
```

The token itself stays in KeePassXC; this only unlocks the database. `keepassxc-cli`
prompts interactively when `KEEPASS_PASSWORD` is unset, which under systemd means the run
fails rather than hangs — a clean failure, but a failure. Setting `SLACK_BOT_TOKEN`
directly in the env file works too and skips KeePassXC entirely, at the cost of a second
copy of the token on disk.

`~/.config/systemd/user/slack-watch.timer`:

```ini
[Unit]
Description=Poll Slack for @claude mentions

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now slack-watch.timer
systemctl --user list-timers slack-watch.timer
journalctl --user -u slack-watch.service -f
```

Run `loginctl enable-linger johnny` so the timer survives you closing the WSL terminal.
**Both are already installed and enabled** — this section documents what was done, not
work still outstanding.

## Usage reporting

Triage replies carry a usage footer:

```
_usage 5h:14% (resets in 4h34m) · 7d:27% (resets in 35h04m) — as of 22m ago_
```

**These numbers come from the statusline cache, not the headless run.** `claude -p
--output-format json` reports per-run token usage only — it does not include the 5h/7d
subscription windows, and nothing on disk holds them. The statusline hook is the only place
Claude Code hands them out, so `~/.claude/statusline-command.sh` now writes them to
`~/.claude/rate-limits-cache.json` on every render.

The consequence, stated plainly: **the figure only refreshes while an interactive session
is running.** If you have been on Slack all day with no terminal open, it will say
"as of 6h ago" — which is why the age is always printed rather than hidden. It is a
useful ceiling ("was I already at 80% when I walked away?"), not a live gauge.

## What it can answer

The watcher routes on intent before doing anything. Not every message needs a chain:

| You type | It does |
|---|---|
| `@claude what were our top customers last month?` | Xero lookup, posts the answer |
| `@claude how's cash looking?` | Xero cash position |
| `@claude did the Moore Wilson's order come through?` | Gmail search |
| `@claude the batch export 500s on save` | clarifies → confirms → `/fix-bug` → MR |
| `@claude can we add CSV export to wastage?` | clarifies → confirms → `/new-feature` → MR |
| `@claude draft an email to that stockist` | declines — outward comms are barred |

**Answers need no confirmation; builds always do.** Reading a Xero number is cheap and
reversible, so it just answers. Launching a chain gets a one-line playback and waits for
"go".

### Sensitive data

`sensitive_data_channels` in `.agents/slack-watch.json` lists channels cleared for detailed
financial and customer data. **It defaults to empty, meaning every channel is uncleared** —
answers come back at shape level ("revenue up on last month, want the breakdown?") rather
than with customer names and figures.

This is the same line `.agents/notifications.json` already draws. Add a channel ID here
only if you're comfortable with customer pricing sitting in scrollback that anyone in the
channel can read forever. A DM with the watcher is the natural place for the cleared list.

## Things worth knowing

**Don't re-tag `@claude` inside a thread the watcher owns.** That wakes the official Claude
app too and you get two agents answering. The watcher says this in its first reply and
follows the whole thread afterwards, so plain replies are enough.

**The thread is untrusted input.** Anyone who can post in that channel can put text in
front of an agent running on your machine with KeePassXC, `glab`, and prod telemetry in
reach. The transcript is fenced in `<thread>` tags and labelled as data, the triage agent
has no Slack access, and the handed-off chain still cannot merge, deploy, or touch a
production database — `.agents/autonomy.md` holds regardless of what a thread says. Widen
the watched channels with that in mind.

**The MR is still the gate.** A handoff runs to a pushed MR and stops. Nothing merges from
Slack.

**First run only looks back one hour.** Otherwise enabling the watcher would answer every
historical `@claude` in the channel at once.

**State lives in `.agents/slack-watch-state.json`** (gitignored). Delete it to reset; the
cost is that recent threads may get answered twice.

## Verified vs. not

**Proven end-to-end against the live Whistlebird workspace:**

- Token resolves from KeePassXC; `auth.test` authenticates as `claude2`
- A real `@claude` mention was discovered, triaged, and **answered in-thread as the
  founder** (not as the bot), with the usage footer rendered correctly
- The systemd timer fires every minute, exits 0, and costs nothing when idle
- Scope, membership, PATH, and session-collision errors all surface with the fix in the
  message
- Post-verification catches an agent that returns a decision without posting

**Bugs that only live data found** — worth knowing, because each was invisible in testing:

| Symptom | Cause |
|---|---|
| Dry run made the real run skip the message | `--dry-run` was persisting the watermark |
| Watcher triaged its own arrival | join notices carry a real `user` and a literal mention |
| Mentions silently ignored | `@claude` autocompletes to `claude2`, not the official app — both IDs must match |
| Every triage failed with ENOENT | systemd's PATH excludes `~/.local/bin`, where `claude` lives |
| `Session ID already in use` | session IDs outlive the state file; deleting state made known threads look new |

**Still unverified:**

- **Xero / Gmail / Drive answer paths.** The routing is written and the tools are
  allow-listed, but no message has actually exercised a connector lookup.
- **The handoff launching a real chain.** No `/fix-bug` or `/new-feature` run has been
  triggered from Slack.
- Behaviour across a WSL restart (lingering is enabled, but untested through a reboot).
- `--once` re-drives a thread but does not reset its status.

The next real bug report posted in `#general` is the test for both unverified paths.
