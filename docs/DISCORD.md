# amebo in Discord

Same bot, different room. It answers when @-mentioned, keeps one conversation
per thread, and offers `/ask`, `/askall` and `/task`. Plain channel chatter is
ignored, exactly as in Slack.

What Discord adds is roles, so anything that changes something outside Discord
is checked against a role before it runs.

## The parts

| File | What it is |
|------|-----------|
| `src/channels/contract.py` | the channel boundary (unchanged, `DISCORD` added) |
| `src/channels/discord_adapter.py` | Discord events in, contract types out |
| `src/channels/discord_policy.py` | who may ask, who may act |
| `src/channels/task_command.py` | the `/task` parser, shared with Slack |
| `src/services/discord_bot.py` | the gateway connection and handlers |
| `src/integrations/govkit_directory.py` | asks GovKit who a Discord user is |

No file names a team. Point the bot at a different instance slug and it is a
different team's bot.

## Setting one up

**1. Discord developer portal** (https://discord.com/developers/applications)

Create an application, add a Bot, copy the token. Then, under Bot →
Privileged Gateway Intents, turn on **Message Content Intent**. Without it
every message arrives with empty text and the bot looks broken rather than
silent.

Invite it with the OAuth2 URL generator: scopes `bot` + `applications.commands`,
permissions View Channels, Send Messages, Send Messages in Threads, Create
Public Threads, Read Message History, Add Reactions.

**2. Environment** — the secret and which instance this process serves:

```
DISCORD_BOT_TOKEN=…
DISCORD_INSTANCE_SLUG=workersvc
```

Both unset means no Discord; the rest of amebo is unaffected.

**3. The instance row** — everything about the particular server, read fresh on
every message, so changing it needs no restart:

```sql
UPDATE instances
SET config = config || '{"discord": {
      "guild_id": "1234567890",
      "govkit_org": "vc",
      "act_roles": ["Steward", "Admin"],
      "act_govkit_roles": ["admin", "steward"],
      "channels": {"allow": [], "deny": []}
    }}'::jsonb
WHERE slug = 'workersvc';
```

- `guild_id` — the one server this instance serves. Unset serves whichever
  server the bot was invited to, which is what you want while setting up.
- `govkit_org` — whose membership rows are the identity map.
- `act_roles` — Discord role **names** that may run acting commands, for people
  GovKit does not know yet.
- `act_govkit_roles` — GovKit roles that may act. Defaults to admin + steward.
- `channels.allow` — empty means every channel. `deny` always wins.

**4. Identity** — a person is known once their GovKit Membership carries their
Discord id (`discord_user_id` on the membership; the bot reads it over the S2S
API at `/api/v1/orgs/{org}/members/by-discord/{id}/`). Set
`GOVKIT_BASE_URL` and `GOVKIT_S2S_TOKEN` for the bot to ask. Without them it
falls back to Discord role names.

## Who may do what

| | Ask questions | Acting commands (`/task`) |
|---|---|---|
| Anyone in the server | yes | no |
| Discord role in `act_roles` | yes | yes |
| GovKit member, role in `act_govkit_roles` | yes | yes |

GovKit is asked first — it is the one home of who a person is. Discord roles
are the fallback for people the org has not enrolled yet. Someone nobody
recognizes can always ask and never act.

## Three ways Discord is not Slack

**Threads are channels, not timestamps.** A top-level mention has to *create* a
thread before there is anything to key the conversation on, so the bot opens
one named after the question and answers inside it. Replies in that thread need
no mention. If it cannot create threads in a channel it answers in the channel
instead — degraded, not broken.

**Messages cap at 2000 characters.** Long answers are split at paragraph, then
line, then word boundaries. Never truncated.

**Private replies only exist as a reply to a slash command.** `/ask` is private
because it is an interaction. A mention cannot be answered privately, which is
why there is no private mention path.

## Checking it

```
python -m src.services.discord_bot     # standalone, for development
```

Otherwise it starts with everything else from `src/main.py`. A Discord failure
is logged and does not take Slack down with it.
