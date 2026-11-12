# amebo on Bluesky

Mention the amebo account on any post and it does the work with Claude Code
on the Max login, the way amebo-max answers Slack. It answers only its owners.

## The parts

| File | What it is |
|------|-----------|
| `backend/src/services/max_answerer.py` | `ClaudeMax`: one Claude Code turn on the Max login, hourly cap, daily rest. Slack's `MaxAnswerer` builds on it |
| `backend/src/services/bluesky_answerer.py` | polls notifications, checks the sender, formats the thread, posts the reply |
| `backend/src/bluesky_answerer.py` | the process: `python -m src.bluesky_answerer` |
| `backend/prompts/amebo-bluesky.md` | added to `amebo-for-claude.md` on Bluesky turns |

## What it does with a mention

1. Polls `listNotifications` every 30 s (no port, no webhook).
2. Skips anything not a mention of, or reply to, the amebo account.
3. Skips senders whose DID is not in `AMEBO_BLUESKY_OWNERS`, silently.
4. Same text scan as Slack (length, injection patterns).
5. Resting or at its hourly cap: leaves the mention and answers it on a later poll.
6. Reads the thread up to 30 posts back, with link cards and quoted posts,
   and runs Claude in that thread's session (one per root post).
7. Replies in the thread; long answers become a chain of at most 4 posts,
   URLs made clickable.

Each handled notification is appended to `AMEBO_BLUESKY_STATE` as it is
handled. First run marks all existing notifications handled.

## Environment (backend `.env`)

| Variable | |
|---|---|
| `AMEBO_BLUESKY_HANDLE` | the bot's handle |
| `AMEBO_BLUESKY_APP_PASSWORD` | an app password (Settings → Privacy and security → App passwords), never the account password |
| `AMEBO_BLUESKY_OWNERS` | handles or DIDs it answers, comma-separated; resolved to DIDs at start |
| `AMEBO_BLUESKY_STATE` | file of handled notification URIs |
| `AMEBO_BLUESKY_PER_HOUR` | default 10 |
| `AMEBO_BLUESKY_SERVICE` | default `https://bsky.social` |

`AMEBO_MAX_WORKDIR`, `AMEBO_MAX_PATH`, `AMEBO_MAX_REPOS`, `AMEBO_MAX_EDIT_DIRS`,
sleep window and timeout are shared with amebo-max.

## Service

Runs as the user who owns the Max login, like `amebo-max.service`:

```
[Unit]
Description=amebo-bluesky: answers the owner's Bluesky mentions with Claude Code on the Max login
After=network-online.target

[Service]
User=<max login owner>
WorkingDirectory=/opt/shared/repos/amebo/backend
EnvironmentFile=/opt/shared/repos/amebo/backend/.env
Environment=AMEBO_MAX_PATH=<same as amebo-max>
Environment=AMEBO_MAX_WORKDIR=/opt/shared/projects
Environment=AMEBO_MAX_REPOS=<same as amebo-max>
ExecStart=/opt/shared/repos/amebo/backend/venv/bin/python -m src.bluesky_answerer
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```
