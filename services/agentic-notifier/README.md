# Diffmogger Agentic Notifier

Agentic Notifier is Diffmogger's reusable local Discord and desktop notification bridge. A target project can call a loopback HTTP API when its Codex automation needs to post progress, message the human owner, or capture an inbound Discord reply. This service owns Discord credentials, channel routing, duplicate suppression, native local notifications, and delivery audit records for notifier activity.

Target projects should not import this code. They only need:

- `POST http://127.0.0.1:8765/api/notify`
- dashboard/SQLite human-message state for canonical requests, replies, outbound records, and resolution notes

## Install

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Real Discord values belong in this service's local `.env`, never in a generated target project and never in Codex-visible task files. Use a virtual environment; do not install packages into Homebrew/system Python if it reports an externally managed environment.

## Discord Setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Add a bot user and copy the bot token into `DISCORD_BOT_TOKEN`.
3. Enable Message Content Intent for inbound replies. Leave Presence Intent and Server Members Intent off.
4. Create two server channels, for example `#diffmogger-progress` and `#diffmogger-messages`.
5. Copy their channel IDs into `DISCORD_PROGRESS_CHANNEL_ID` and `DISCORD_MESSAGING_CHANNEL_ID`.
6. Invite the bot with the OAuth2 URL Generator. For Diffmogger, check only the `bot` scope. After you check `bot`, Discord reveals a separate **Bot Permissions** section below the scopes list. In that permissions section, check View Channels, Send Messages, and Read Message History.
7. Copy the generated URL, open it in your browser, choose your Discord server, and authorize the bot. You need permission to add apps/bots to that server.

### Channel ID Checklist

Discord only shows channel IDs when Developer Mode is enabled:

1. In Discord, open **User Settings -> Advanced**.
2. Turn on **Developer Mode**.
3. Go to your server and right-click the progress channel, for example `#diffmogger-progress`.
4. Click **Copy Channel ID** and paste it into `DISCORD_PROGRESS_CHANNEL_ID`.
5. Right-click the messaging channel, for example `#diffmogger-messages`.
6. Click **Copy Channel ID** and paste it into `DISCORD_MESSAGING_CHANNEL_ID`.

Channel IDs are long numeric strings. They are not secrets, but keep them in `services/agentic-notifier/.env` with the rest of the notifier configuration so target projects stay generic.

### OAuth2 URL Generator Checklist

In the Developer Portal, open your application, then go to **OAuth2 -> URL Generator**.

Under **Scopes**, check:

```text
bot
```

Do not check `identify`, `email`, `guilds`, `messages.read`, `webhook.incoming`, or `applications.commands` for the basic Diffmogger notifier. Those are OAuth2 scopes, not the normal server/channel permissions Diffmogger needs. In particular, `messages.read` is not the same as the **Read Message History** bot permission.

After checking `bot`, scroll down to the **Bot Permissions** section. That section is not visible until `bot` is selected. Check:

```text
View Channels
Send Messages
Read Message History
```

In Discord's permission groups, **View Channels** is under general permissions. **Send Messages** and **Read Message History** are under text permissions.

Do not check `Administrator`. The minimum permission integer for those three permissions is `68608`, so a manually inspected invite URL may contain:

```text
scope=bot&permissions=68608
```

Copy the generated URL at the bottom of the page, open it, select the server, and approve the install. After installation, confirm the bot can see both configured channels. If either channel has custom permission overwrites, grant the bot or its role View Channel, Send Messages, and Read Message History in that channel.

Message Content Intent is not part of the OAuth2 URL. Enable it separately under **Bot -> Privileged Gateway Intents** so Diffmogger can capture reply messages that do not mention the bot directly.

### Privileged Gateway Intents Checklist

In the Developer Portal, open your application, then go to **Bot -> Privileged Gateway Intents**.

Turn on:

```text
Message Content Intent
```

Leave these off:

```text
Presence Intent
Server Members Intent
```

Diffmogger does not read presence updates or member lists. It does request message content through `discord.py` so it can capture human replies in the messaging channel. If Message Content Intent is off while `DRY_RUN=false`, Discord may reject the bot connection with a privileged-intents error.

References:

- [Discord bot docs](https://docs.discord.com/developers/bots)
- [Discord OAuth2 and permissions docs](https://docs.discord.com/developers/platform/oauth2-and-permissions)

## Target Project Records

Set `TARGET_REPO_DIR` to the absolute path of the target project. Diffmogger automation should treat `.diffmogger/runtime/orchestration.sqlite3` as the canonical human-message state. The notifier's optional Markdown/JSONL outputs are delivery audit projections, not the live queue.

If explicit audit paths are left unset, the service uses sidecar Markdown audit paths for targets with `.diffmogger/manifest.json`, or `docs/` paths for older targets:

```text
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
```

The notifier creates these audit files if missing. Target automation should record handled replies, outbound delivery failures, and resolution notes in typed dashboard/SQLite human-message state.

Optional JSONL queues can also be enabled:

```text
TARGET_QUEUE_DIR=/absolute/path/to/target-project/queue
```

When set, the notifier appends `human_requests.jsonl`, `human_outbox.jsonl`, and `human_responses.jsonl` in that directory in addition to Markdown audit records.

## Run

Default one-process runner:

```bash
python -m agentic_notifier.run_service
```

Default local API:

```text
http://127.0.0.1:8765
```

The Discord bot and API run in the same process. In `DRY_RUN=true`, API calls write audit records when target paths are configured and report dry-run deliveries without sending Discord or desktop notifications.

## Health

```bash
curl http://127.0.0.1:8765/health
```

The health response includes whether the target repo is configured, Discord token/channel settings are present, local notifications are enabled, and dry-run mode is active.

## Notify API

Target projects call:

```text
POST http://127.0.0.1:8765/api/notify
```

Progress payload:

```json
{
  "request_id": "PROG-2026-04-29-001",
  "type": "automation_progress",
  "priority": "normal",
  "summary": "Builder integrated one patch",
  "event_kind": "progress",
  "message_body": "Builder integrated one patch and verification passed.",
  "dedupe_key": "PROG-2026-04-29-001:v1",
  "expects_reply": false,
  "local_notify": false
}
```

Direct human-message payload:

```json
{
  "request_id": "MSG-2026-04-29-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "event_kind": "message",
  "message_body": "Project update: Built X, Y, and Z. Checks passing: tests/build. Current blocker: none.",
  "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "unblocked_work_remaining": [
    "Continue current automation sprint"
  ],
  "dedupe_key": "MSG-2026-04-29-001:v1",
  "expects_reply": false
}
```

Human-unlock request payload:

```json
{
  "request_id": "HR-2026-04-29-001",
  "type": "api_key_setup",
  "priority": "unlocking",
  "summary": "Add Service X read-only API key",
  "event_kind": "message",
  "context": "This unlocks the next source adapter while offline fixtures remain available.",
  "agent_recommendation": "Use read-only/data-only access. Do not grant write, billing, admin, or production permissions.",
  "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
  "reply_format": "HR-001 DONE or HR-001 SKIP",
  "unblocked_work_remaining": [
    "Continue fixture-based dashboard work",
    "Continue report polish"
  ],
  "dedupe_key": "HR-2026-04-29-001:v1"
}
```

Response:

```json
{
  "ok": true,
  "request_id": "MSG-2026-04-29-001",
  "sent": true,
  "dry_run": false,
  "deduped": false,
  "message_preview": "Project update: Built X, Y, and Z...",
  "deliveries": {
    "discord": {
      "enabled": true,
      "ok": true,
      "sent": true,
      "dry_run": false,
      "status": "sent",
      "detail": ""
    },
    "local": {
      "enabled": true,
      "ok": true,
      "sent": true,
      "dry_run": false,
      "status": "sent",
      "detail": "macOS desktop notification delivered"
    }
  }
}
```

Delivery failures are returned with generic statuses such as `DISCORD_SEND_FAILED`, `LOCAL_NOTIFICATION_FAILED`, or `NOTIFIER_UNREACHABLE` and mirrored to audit records when configured. Target automations should also record those statuses in typed human-message state, and should not claim delivery unless the notifier response shows success or dry-run intent.

If `LOCAL_NOTIFY_API_TOKEN` is set, include:

```text
Authorization: Bearer <token>
```

Without a token, the API must remain bound to loopback.

## Channel Routing

- `event_kind: "progress"` posts to `DISCORD_PROGRESS_CHANNEL_ID`.
- `event_kind: "message"` posts to `DISCORD_MESSAGING_CHANNEL_ID`.
- Generated multi-role targets in `discord_notifier` mode send `progress` notifications after local automation commits, including the commit subject and short work summary.
- Blockers that need user input, human-unlock requests, and replies to user messages should use `message`.
- Direct user messages default to local desktop notifications when `LOCAL_NOTIFICATIONS_ENABLED=true`.
- Completion/progress events can set `local_notify: true` when they should also alert locally.

## Discord Inbound Replies

The bot only reads the configured messaging channel. It ignores bot messages and captures human messages only when they mention the bot or reply to a bot-authored message.

Captured messages are mirrored to the audit inbox when target paths are configured:

```text
.diffmogger/state/HUMAN_INBOX.md
```

Inbound messages are deduped by Discord message ID. The next target automation run should handle the message through typed dashboard/SQLite human-message state, mark it resolved only after the requested action is complete or intentionally deferred, and record a concise resolution note.

## Dry-Run Tests

The default `.env.example` uses `DRY_RUN=true`. The example config starts with `DRY_RUN=true`.

```bash
python scripts/send_test_notification.py --progress
python scripts/send_test_notification.py
python scripts/dry_run_inbound.py "@Diffmogger HR-001 DONE. Key added locally."
```

Use `--real-send` only after Discord channels, bot permissions, and target-side human-message handling are verified.

## Safety

- Keep Discord tokens only in `services/agentic-notifier/.env`.
- Bind the API to `127.0.0.1` unless `LOCAL_NOTIFY_API_TOKEN` is configured.
- Do not put Discord tokens or channel IDs in target-project task files or prompts.
- Use `DRY_RUN=true` until setup is verified.
- Keep target projects decoupled from notifier implementation internals.

## Tests

```bash
python -m pytest
```

Tests use fake Discord senders and local-notification dry-run/failure paths. They do not require real Discord credentials.
