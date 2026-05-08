# Human Bridge

The human bridge lets Codex ask for meaningful manual unlocks without blocking the whole automation workflow.

## When To Ask

Ask the human for:

- account/API setup
- paid-tier approval
- deployment/domain setup
- high-impact product direction
- risky external side effects
- environment fixes only the human can perform

Do not ask for routine implementation choices. Pick a safe default and document it.

## Modes

Diffmogger supports:

- `file_only`: Markdown queues and dashboard messages only.
- `local_notifier`: Markdown files plus native local desktop notifications through the loopback notifier API.
- `discord_notifier`: Discord progress/messages plus optional native local desktop notifications.
- `disabled`: no human bridge files required.

In `file_only` mode, if the human writes `send me a summary`, `status update`, or similar in `.diffmogger/state/HUMAN_INBOX.md`, the automation should answer locally in Markdown or an app artifact. It should not call notifier APIs unless the target project is explicitly configured for notifier mode.

## Markdown Files

Enabled bridge modes use:

```text
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
```

Codex writes requests. The human or notifier writes replies in `HUMAN_INBOX.md`. A later run handles the reply, removes it only after the requested action is complete or intentionally deferred, and appends a concise archive entry.

## Bundled Notifier Service

Diffmogger includes a reusable notifier service:

```text
services/agentic-notifier/
```

Target project automation may call:

```text
POST http://127.0.0.1:8765/api/notify
```

The notifier owns:

- Discord bot credentials and channel routing
- native macOS desktop notifications
- outbound and inbound dedupe
- target Markdown handoff writes
- dry-run mode
- optional JSONL queue files

Target projects must not import notifier code, inspect notifier internals during normal runs, or handle Discord credentials.

## Notify API Shape

Progress events use `event_kind: "progress"` and route to the Discord progress channel when `discord_notifier` is configured. In multi-role automation, each local commit created by `.diffmogger/scripts/integrate_role_outputs.py` triggers a brief progress notification with the commit subject and work summary.

Direct human messages use `event_kind: "message"` and route to the Discord messaging channel when configured. Human-unlock requests, blockers that need user input, and replies to user messages also use `event_kind: "message"`. They default to local desktop notifications when local notifications are enabled.

Example direct message:

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

Ticket completion and terminal blocker notifications should use `event_kind: "progress"` and set `local_notify: true` when the human should also receive a local desktop notification.

If the notifier is unavailable:

1. Do not claim a message was delivered.
2. Write the intended message to `.diffmogger/state/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.
3. Keep or annotate the inbox entry as unresolved if a response is still required.
4. Continue useful work where possible.

The notifier records delivery failures with generic statuses such as `DISCORD_SEND_FAILED`, `LOCAL_NOTIFICATION_FAILED`, and `NOTIFIER_UNREACHABLE`.

## Discord Inbound Replies

In `discord_notifier` mode, the bot reads only the configured messaging channel. It ignores bot messages and captures human messages only when they mention the bot or reply to a bot-authored message.

Captured messages are appended to `.diffmogger/state/HUMAN_INBOX.md` with Discord metadata and deduped by Discord message ID.

## Running The Bundled Service

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m agentic_notifier.run_service
```

The example config starts with `DRY_RUN=true`; change it only after target files, Discord channels, and local notifications are verified.

## Discord Setup

1. Create a Discord application and bot.
2. Copy the bot token into `DISCORD_BOT_TOKEN` in `services/agentic-notifier/.env`.
3. Enable Message Content Intent for inbound replies. Leave Presence Intent and Server Members Intent off.
4. Create a progress channel and messaging channel, then set `DISCORD_PROGRESS_CHANNEL_ID` and `DISCORD_MESSAGING_CHANNEL_ID`.
5. Invite the bot with the OAuth2 URL Generator. Check only the `bot` scope. After `bot` is checked, Discord shows a separate **Bot Permissions** section below the scopes list. In that section, check View Channels, Send Messages, and Read Message History.
6. Copy the generated URL, open it, choose your server, and authorize the bot. The invite URL may show `scope=bot&permissions=68608`.

To get channel IDs, enable **User Settings -> Advanced -> Developer Mode** in Discord. Then right-click the progress channel, choose **Copy Channel ID**, and paste it into `DISCORD_PROGRESS_CHANNEL_ID`. Do the same for the messaging channel and `DISCORD_MESSAGING_CHANNEL_ID`.

Do not check `identify`, `email`, `guilds`, `messages.read`, `webhook.incoming`, `applications.commands`, or `Administrator` for the basic Diffmogger notifier. `messages.read` is an OAuth2 scope and is not the same as the **Read Message History** bot permission.

Message Content Intent is enabled separately under **Bot -> Privileged Gateway Intents**. It is not an OAuth2 URL checkbox. Turn on only **Message Content Intent**; leave **Presence Intent** and **Server Members Intent** off. Diffmogger does not read presence updates or member lists.

Official references:

- [Discord bot docs](https://docs.discord.com/developers/bots)
- [Discord OAuth2 and permissions docs](https://docs.discord.com/developers/platform/oauth2-and-permissions)
