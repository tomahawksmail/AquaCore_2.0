# AquaCore 2.0 — Native Armbian deployment (NO Docker)

**Status: deployment instructions in testing; validate on Orange Pi Zero 2W / Armbian 26.11 before controlling powered loads.**

## 1. System packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates python3 python3-venv python3-pip python3-dev build-essential pkg-config libgpiod-dev gpiod mariadb-server mariadb-client
```

## 2. Install repository in /opt/aquacore
```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin aquacore || true
sudo git clone https://github.com/tomahawksmail/AquaCore_2.0.git /opt/aquacore
sudo chown -R aquacore:aquacore /opt/aquacore
sudo -u aquacore python3 -m venv /opt/aquacore/.venv
sudo -u aquacore /opt/aquacore/.venv/bin/pip install -U pip
sudo -u aquacore /opt/aquacore/.venv/bin/pip install -r /opt/aquacore/requirements.txt
/opt/aquacore/.venv/bin/python -c 'import gpiod; print(gpiod.__version__)'
```
A private repo requires authenticated Git access. Use your private credential manager, not a token embedded in a URL.

## 3. Database
```bash
sudo systemctl enable --now mariadb
sudo mariadb
```
Inside the MariaDB console (replace placeholders):
```sql
CREATE DATABASE IF NOT EXISTS \`_AquaCore_\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'aquacore_web'@'localhost' IDENTIFIED BY 'REPLACE_WITH_LONG_RANDOM_SECRET';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE ON \`_AquaCore_\`.* TO 'aquacore_web'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```
**Important:** Creating an empty database is not sufficient. AquaCore expects its existing `data`, `psutil`, `status`, `options`, `manual_overrides`, `loging`, and account tables. Restore your **existing AquaCore schema and data from your trusted SQL backup**, then verify. Do not guess account schema or enable relays against an uninitialized database.
```bash
sudo mariadb -e 'SHOW TABLES FROM \`_AquaCore_\`;'
```

## 4. Private environment
Create `/etc/aquacore/web.env` with root ownership and mode 600; systemd loads this file for every service:
```bash
sudo install -d -m 700 /etc/aquacore
sudo nano /etc/aquacore/web.env
```
Example values (replace every placeholder):
```ini
DB_HOST=localhost
DB_NAME=_AquaCore_
DB_USER=aquacore_web
DB_PASSWORD=REPLACE_WITH_LONG_RANDOM_SECRET
SECRET_KEY=REPLACE_WITH_RANDOM_HEX_SECRET
BOT_TOKEN=REPLACE_WITH_PRIVATE_TELEGRAM_BOT_TOKEN
MyTGaccount=REPLACE_WITH_NUMERIC_TELEGRAM_USER_ID
COOKIE_SECURE=true
AQUACORE_BIND=127.0.0.1:5001
AQUACORE_WORKERS=2
```
```bash
sudo chmod 600 /etc/aquacore/web.env
sudo chown root:root /etc/aquacore/web.env
```
No secrets in Git. The older `.env` is not necessary when running systemd services with EnvironmentFile.

## Manual testing — no systemd services

Do not start web, scheduler or Telegram units. Run each command in a separate SSH terminal. The `/etc/aquacore/web.env` file is root-only, so each command loads it in a root shell before dropping permissions where possible.

**Terminal 1: Flask web app (Gunicorn)**

```bash
sudo bash -c '
  set -a
  . /etc/aquacore/web.env
  set +a
  cd /opt/aquacore
  exec runuser -u aquacore -- .venv/bin/gunicorn --config gunicorn.conf.py wsgi:app
'
```
Open from Orange Pi: `curl -I http://127.0.0.1:5001/login`. It binds to localhost until Tailscale is configured.

**Terminal 2: scheduler**

```bash
sudo bash -c '
  set -a
  . /etc/aquacore/web.env
  set +a
  cd /opt/aquacore
  exec runuser -u aquacore -- .venv/bin/python scheduler.py
'
```
The scheduler **writes equipment schedule states** into the restored MariaDB `status` table but cannot energize relays unless a live relay worker is also running.

**Terminal 3: Telegram**

```bash
sudo bash -c '
  set -a
  . /etc/aquacore/web.env
  set +a
  cd /opt/aquacore
  exec runuser -u aquacore -- .venv/bin/python telegram_bot.py
'
```

**Optional terminal 4: relay read-only/dry-run**

```bash
sudo bash -c '
  set -a
  . /etc/aquacore/web.env
  set +a
  cd /opt/aquacore
  exec .venv/bin/python relay_controller.py
'
```
This prints desired aquarium and cooler states without changing GPIO. When ready to test with aquarium and mains loads disconnected, explicitly use `--apply`. The fan output is active-low; GPIO 232 LOW means relay closed. Cooler activates above 70 C, deactivates at/below 65 C; intermediate values retain previous cooler state. On missing/invalid CPU temperature it requests cooler ON as a precaution. Temperature is read from `/sys/class/thermal/thermal_zone0/temp`; verify your actual CPU sensor before trusting this automated control. Cooler motor must have its own appropriately rated power source, not draw motor power from Orange Pi GPIO.

Stop each manually launched process with Ctrl+C. Do not start duplicate copies of the same application or GPIO controller.

## 5. Install native services
```bash
sudo cp /opt/aquacore/deploy/systemd/aquacore.service /etc/systemd/system/
sudo cp /opt/aquacore/deploy/systemd/aquacore-telegram.service /etc/systemd/system/
sudo cp /opt/aquacore/deploy/systemd/aquacore-scheduler.service /etc/systemd/system/
sudo cp /opt/aquacore/deploy/systemd/aquacore-relays.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aquacore.service aquacore-telegram.service aquacore-scheduler.service
sudo systemctl status aquacore.service aquacore-telegram.service aquacore-scheduler.service --no-pager
curl -I http://127.0.0.1:5001/login
```
Do **not** enable `aquacore-relays.service` yet.

## Relay GPIO assignment (user-tested)

| Relay channel | Equipment | SoC pin | gpiochip1 offset | Physical header pin |
| --- | --- | --- | ---: | ---: |
| 1 | CO2 | PH4 | 228 | 18 |
| 2 | Oxygen | PI6 | 262 | 22 |
| 3 | Main light | PH5 | 229 | 24 |
| 4 | Unused | PH9 | 233 | 26 |
| 5 | Backlight | PI16 | 272 | 37 |
| 6 | Plant light | PC12 | 76 | 36 |
| 7 | UV | PI0 | 256 | 29 |
| 8 | Reserved | PH6 | 230 | 23 |
| 9 | CPU cooler (ON above 70 C; OFF at/below 65 C) | PH8 | 232 | 21 |
| 10 | Reserved | PH7 | 231 | 19 |

## 6. Validate relays safely
Stop any manual `gpioset` tests and physically disconnect mains/aquarium loads. Verify that offsets match your actual header wiring and that outputs are active-low:
```bash
gpioinfo -c gpiochip1 | grep -E 'line +(228|262|229|272|76|256|232):'
sudo /opt/aquacore/.venv/bin/python /opt/aquacore/relay_controller.py --interval 1
```
This is dry-run mode. It reads DB states and logs requested outputs without touching GPIO. Ctrl+C to end. The relay worker now uses persistent `libgpiod 2` line ownership in `--apply` mode; six channels are CO2 PH4(228), Oxygen PI6(262), Main PH5(229), Backlight PI16(272), Plant PC12(76), UV PI0(256). Three other lines remain unclaimed (PH9/233, PH6/230, PH7/231); the CPU cooler uses PH8/232. **On startup the active-low relay lines initialize HIGH/OFF, and switch based on DB state.** Releasing lines on exit may not preserve voltage; use external hardware fail-safe arrangements.
After verifying the database schedule/state and physical relay wiring, explicitly enable live control:
```bash
sudo systemctl enable --now aquacore-relays.service
sudo journalctl -u aquacore-relays.service -n 50 --no-pager
```

## 7. Tailscale HTTPS
The Tailscale install script is **still in testing**.
```bash
sudo bash /opt/aquacore/deploy/setup_tailscale_https.sh
```
It verifies that the device's actual assigned hostname is `aquacore.orangepi.ts.net` before configuring private Serve to `127.0.0.1:5001`. MagicDNS and HTTPS certificates must be enabled in Tailscale DNS settings. Your PC/phone must be authorized in the same tailnet. Do not enable Funnel or router port forwarding.

## 8. Maintenance
```bash
sudo journalctl -u aquacore.service -f
sudo journalctl -u aquacore-telegram.service -f
sudo journalctl -u aquacore-scheduler.service -f
sudo journalctl -u aquacore-relays.service -f
```
Update:
```bash
cd /opt/aquacore
sudo systemctl stop aquacore-relays.service
sudo git pull --ff-only origin master
sudo -u aquacore /opt/aquacore/.venv/bin/pip install -r /opt/aquacore/requirements.txt
sudo systemctl daemon-reload
sudo systemctl restart aquacore.service aquacore-telegram.service aquacore-scheduler.service
# Only after retesting GPIO logic and wiring:
# sudo systemctl start aquacore-relays.service
```

## Testing criteria
Verify SSH, MariaDB connectivity/schema, login and CSRF, scheduler mode, Telegram owner and additional users, relay input polarity, relay behavior during DB outage, Tailscale certificate/access, reboot persistence and power-loss/recovery **before connecting mains equipment**.
