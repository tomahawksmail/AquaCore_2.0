# AquaCore Telegram bot

This is a separate aiogram 3 polling process for AquaCore 2.0, using **existing MariaDB tables**. It does not control GPIO directly. The scheduler must run to expire overrides; relay_controller must run with --apply to actuate hardware.

## Requirements

Set these in the project's private .env file (or the service's protected environment file):

```ini
BOT_TOKEN=your_existing_telegram_bot_token
MyTGaccount=your_numeric_telegram_user_id
```

Use your existing database credentials (DB_HOST/DB_USER/DB_PASSWORD/DB_NAME, or HOST/USER/PASSWORD/DATABASE). Do not commit secrets.

## Test

```bash
cd /home/orangepi/AquaCore
git pull origin master
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python telegram_bot.py
```

In Telegram, open a **private chat** with your bot and send /start. It silently ignores other accounts and group chats. A numeric MyTGaccount is required. Avoid logging token values. Only **one** polling instance should run for the same token.

## Commands

- /start : inline menu
- /aqua : most recent water sample, timestamp and missing-data warning
- /system : latest psutil metrics
- /equipment : requested ON/OFF and manual/auto status for six configured devices
- /settings : current thresholds and six equipment schedules
- /set FIELD VALUE : update one validated setting; e.g. /set max_tds 500, /set co2_on 08:00
- /help : commands

To control equipment, choose Equipment and select ON/OFF/AUTO. **Every switching action requires a second confirmation.** ON/OFF applies manual override only until the **next configured schedule transition**; AUTO immediately removes the override and applies the calculated scheduled state. Actions and settings changes are logged in `loging` with the Telegram user ID. Relay state is a **software request, not hardware feedback**.

The bot does NOT offer remote shell access, arbitrary SQL, arbitrary GPIO numbers, or control for heater and unassigned relay channels 7–10.

## systemd (if project installed at /opt/aquacore)

```bash
sudo cp deploy/systemd/aquacore-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aquacore-telegram
sudo journalctl -u aquacore-telegram -f
```

If instead running from /home/orangepi/AquaCore, adjust WorkingDirectory, ExecStart, and user/group **before** installing this service. `ProtectHome=true` prevents reading files in /home, so don't use this service unchanged with a home-directory installation.

Security: Keep BOT_TOKEN private, consider rotating it after exposure, restrict .env permissions, keep the bot and OS updated, and never put a bot token in an Nginx URL or Git repository. Commands check the initiating Telegram user ID **and private chat ID**; the bot uses polling, not a public Telegram webhook. Telegram transport and bot trust are not equivalent to end-to-end encryption; avoid transmitting secrets in messages.

## Settings and additional Telegram users

Settings is a reply-keyboard submenu: **Water limits**, **Timings**, and (owner-only) **Telegram users**. Select a specific limit or scheduled ON/OFF field, then enter a validated number or HH:MM. Changes are persisted to `options` with an audit-log entry.

The bot persists additional Telegram IDs in a `telegram_users` MariaDB table, created on startup if the database user has CREATE privilege. The database user must have SELECT, INSERT, UPDATE and DELETE on this table. If the production app database user does not have CREATE permission, a database administrator must run the following once:

```sql
CREATE TABLE IF NOT EXISTS telegram_users (
    telegram_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    role VARCHAR(16) NOT NULL DEFAULT 'viewer',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Grant SELECT, INSERT, UPDATE, DELETE on the table to the app's exact MariaDB account.
```

**Owner** is always the numeric `MyTGaccount` from the private .env file. Only owner can add a viewer, add an operator, or remove users, using numeric Telegram IDs and a confirmation step. Viewer can read metrics, charts and existing settings; operator can also change equipment and scheduled times. The bot checks permissions on each incoming message and only accepts private chats whose chat ID equals the sender's Telegram ID. Added users must first open the bot and send /start. Access revocation is effective on their next message. Do not grant operator privileges to untrusted people: equipment commands can affect pumps, CO2, lights, and UV.

Restart the running polling process after updating; do not run two copies for one token.
