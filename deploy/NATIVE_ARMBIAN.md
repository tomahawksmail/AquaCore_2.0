## Fertilizer database consolidation — use options + status (November 2026)

**This section supersedes the older fertilizer_pump-table installation and migration examples later in this document. The running application and relay worker no longer read that old table.**

- `options.fertilizer_start_time`, `options.fertilizer_dose_ml`, `options.fertilizer_ml_per_second` store schedule and flow.
- Remaining `options.fertilizer_*` columns keep request IDs, completion dates, pulse state and calibration progress.
- `status.fertilizer_pump_status` is the relay worker's requested ON/OFF state: `checked` when commanded ON, `unchecked` when commanded OFF. This is **not** a hardware feedback signal or verified flow measurement.

### Safe upgrade (with existing fertilizer_pump data)

1. Keep the pump's outlet disconnected from the aquarium. Stop both services before migrating.
2. Make a database backup, pull the new code and add the new options columns.
3. Copy the old table's values **once** while stopped. This intentionally marks old queued requests as processed, so they cannot replay.
4. Verify the copied columns and service logs. Only after successful testing should you drop the legacy table.

```bash
sudo systemctl stop aquacore.service aquacore-relays.service
sudo mariadb-dump _AquaCore_ > ~/aquacore-before-fertilizer-options.sql
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master

# Run even if the previous fertilizer_pump table was already dropped:
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_options.sql

# ONLY if old fertilizer_pump still exists; do this once before deleting it:
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_options_copy.sql

sudo mariadb _AquaCore_ -e "
  SELECT fertilizer_start_time,fertilizer_dose_ml,
         fertilizer_ml_per_second,fertilizer_manual_request_id,
         fertilizer_manual_processed_id,fertilizer_pulse_state
    FROM options;"
sudo mariadb _AquaCore_ -e "
  SELECT fertilizer_pump_status FROM status;"

sudo systemctl start aquacore.service aquacore-relays.service
sudo systemctl status aquacore.service aquacore-relays.service --no-pager
sudo journalctl -u aquacore-relays.service -n 60 --no-pager
```

**If the old table was already deleted**, omit `fertilizer_options_copy.sql`. New columns default to a disabled 0 mL daily dose and no saved pump calibration, so re-calibrate after confirming the relay worker works. The Manual ON/OFF switch remains available independently of calibration, with a 30-second automatic cutoff. **Never** run the legacy `fertilizer_pump.sql`, `fertilizer_manual.sql`, `fertilizer_ml.sql` or `fertilizer_progress.sql` migrations on new installations.

After verifying the web Settings page, a short manual ON/OFF test with a water-filled measuring cup, and the new calibration progress, **you may remove the old table**:

```bash
# Only after copying/backing up data and confirming both services work:
sudo mariadb _AquaCore_ -e 'DROP TABLE IF EXISTS `fertilizer_pump`;'
```

No new service is needed. The relay controller owns GPIO 230 and publishes its commanded state to `status`. The settings popup and `/api/fertilizer/status` now read `options`. The old SQL files remain in GitHub only as historical references.

---

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
| 4 | Fertilizer dosing pump | PH6 | 230 | 23 |
| 5 | Backlight | PI16 | 272 | 37 |
| 6 | Plant light | PC12 | 76 | 36 |
| 7 | UV | PI0 | 256 | 29 |
| 8 | Reserved (former pump) | PH9 | 233 | 26 |
| 9 | CPU cooler (ON above 70 C; OFF at/below 65 C) | PH8 | 232 | 21 |
| 10 | Reserved | PH7 | 231 | 19 |

## 6. Validate relays safely
Stop any manual `gpioset` tests and physically disconnect mains/aquarium loads. Verify that offsets match your actual header wiring and that outputs are active-low:
```bash
gpioinfo -c gpiochip1 | grep -E 'line +(228|262|229|272|76|256|232):'
sudo /opt/aquacore/.venv/bin/python /opt/aquacore/relay_controller.py --interval 1
```
This is dry-run mode. It reads DB states and logs requested outputs without touching GPIO. Ctrl+C to end. The relay worker now uses persistent `libgpiod 2` line ownership in `--apply` mode; six channels are CO2 PH4(228), Oxygen PI6(262), Main PH5(229), Backlight PI16(272), Plant PC12(76), UV PI0(256). Two other lines remain unclaimed (PH7/231, PH6/230); the CPU cooler uses PH8/232 and the fertilizer pump uses PH6/230. **On startup the active-low relay lines initialize HIGH/OFF, and switch based on DB state.** Releasing lines on exit may not preserve voltage; use external hardware fail-safe arrangements.
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

## ADS1115 TDS database collector (provisional ppm)

The ADS1115 ADC has been detected at **I2C bus 2, address 0x48**, with the analog TDS transmitter connected to **A3**. `tds_collector.py` samples A3, applies the same temperature-compensated DFRobot-style polynomial as `sensorstest.py`, and multiplies by the **provisional 0.2626 factor** derived by assuming boiled Primo water was 13 ppm. **This is not a true calibration.** Default water temperature is **22 C**, manually estimated; change `--temperature` when water temperature changes.

Only `data.tds` receives a measured value; `data.temp` and `data.ph` are inserted as `NULL`, because those probes have not been configured. One row is written every 30 seconds, using MariaDB `NOW()`; errors do not insert fake TDS readings. The scheduler's missing-data zero fallback still applies after 60s without any rows.

### One-time test before enabling service
```bash
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo usermod -aG i2c aquacore
sudo bash -c '
set -a
. /etc/aquacore/web.env
set +a
cd /opt/aquacore
exec runuser -u aquacore -- .venv/bin/python tds_collector.py --bus 2 --temperature 22 --once
'
sudo mariadb _AquaCore_ -e 'SELECT Id,Datetime,temp,ph,tds FROM data ORDER BY Id DESC LIMIT 3;'
```

### Enable native service
```bash
sudo cp /opt/aquacore/deploy/systemd/aquacore-tds.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aquacore-tds.service
sudo journalctl -u aquacore-tds.service -n 30 --no-pager
```

If I2C is denied, verify `getent group i2c`, `ls -l /dev/i2c-2` and the service's `SupplementaryGroups=i2c`. Do not start an additional copy of the collector manually while the service runs.

**Electrical caution:** The ADC was earlier powered at 5 V while its I2C pins directly connected to the Orange Pi's 3.3 V GPIO. Use a proper level shifter or power ADS1115 at 3.3 V with analog voltage in range before running continuously. The TDS transmitter can remain at 5 V if its actual analog output stays within the ADC supply and input limits.

## Fertilizer pump — once-daily timed pulse

Dedicated GPIO: **gpiochip1 offset 230 / PH6 / physical header pin 23** (active-low; LOW energizes relay).

The relay worker already runs as `aquacore-relays.service`; no separate process is required. The Settings page provides two auto-saved fields: **Activation time (HH:MM)** and **Run duration in seconds (0–60)**. Default is **12:00 with 0 seconds**, meaning **OFF/disabled** until explicitly configured.

**Database migration — required before deploying the updated web application and relay worker:**
```bash
sudo systemctl stop aquacore-relays.service aquacore.service
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_pump.sql
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_manual.sql
sudo mariadb _AquaCore_ -e 'SELECT * FROM fertilizer_pump;'
sudo systemctl start aquacore.service
# Only after checking dosing settings and disconnected pump:
sudo systemctl start aquacore-relays.service
```

The relay worker checks the DB-local clock during the first 10 seconds of the scheduled minute, atomically records the date as consumed **before** switching the pump ON, and switches OFF via a timer after the duration. Missed schedules are not replayed; a restart after a claimed dose will not repeat it. A dose may be skipped if the process fails between claiming and activating. Stopping the service requests pump OFF, but no software can guarantee an output level during loss of power; use a normally-open relay with a safe de-energized default.

**Testing:** keep pump and aquarium loads disconnected while setting a 1–2 second duration and a time a few minutes ahead. Watch:
```bash
sudo journalctl -u aquacore-relays.service -f
sudo mariadb _AquaCore_ -e 'SELECT * FROM fertilizer_pump;'
```
Confirm GPIO 230 switches only once and returns OFF promptly, including after relay-worker restart. Change duration back to 0 until the pump has been calibrated for delivered milliliters. Use appropriate external pump supply and protect against siphoning and unintended dosing; don't power the pump motor from the Orange Pi GPIO.

### Manual fertilizer dose (Settings → Equipment & lighting)

The fertilizer pump now appears under the **Equipment & lighting** card alongside the scheduled relays. Set **Activation time** and **Run duration (0–60 seconds)** there. **Dose now** requests one additional pulse using the saved duration; it does not replace or consume the scheduled daily dose.

- Requires the admin role, authenticated session, confirmation dialog, and CSRF token.
- Requests are placed in MariaDB; only the existing `aquacore-relays.service` energizes GPIO 230.
- The endpoint allows one pending request and applies a **120-second cooldown** between manual requests. The relay worker marks a request processed **before** output activation, preventing repeat dosing after a restart.
- Any pending request older than 15 seconds is discarded rather than executed late.
- Manual and scheduled pulses cannot overlap in the same worker. If a scheduled dose falls while the pump is busy, that day's scheduled dose may be skipped.
- Button success means **queued**, not verified delivered. Confirm via `sudo journalctl -u aquacore-relays.service -f`.
- Manual dose requests add fertilizer **on top of** automatic dosing, so use short test durations with the pump disconnected until the measured delivered volume is established.

If upgrading an existing database, run the new `fertilizer_manual.sql` migration **before starting the new Flask and relay code**. The SQL script can be rerun safely on MariaDB supporting `ADD COLUMN IF NOT EXISTS`.

## Calibrated fertilizer dosing in milliliters (replaces seconds)

**Existing installations:** Stop both `aquacore.service` and `aquacore-relays.service`, update the checkout, then run this migration before restarting either unit:
```bash
sudo systemctl stop aquacore.service aquacore-relays.service
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_ml.sql
sudo mariadb _AquaCore_ -e 'SELECT start_time,dose_ml,ml_per_second FROM fertilizer_pump;'
sudo systemctl start aquacore.service aquacore-relays.service
```

**Important:** After migration, `dose_ml=0` and `ml_per_second=NULL` (disabled until calibration). The old `duration_seconds` setting is **ignored**. If starting from an empty DB instead, use the updated `fertilizer_pump.sql` schema. Existing installations must already have `fertilizer_manual.sql` fields.

### Calibrate with a measuring cup

1. Prime the pump and route its tube into a measuring cup **outside the aquarium**.
2. Open **Settings → Equipment & lighting → Fertilizer pump → Pump calibration**.
3. Click **Run 10-second test**, then confirm. The request is queued and expires if relay service does not handle it within 15 seconds.
4. Inspect `sudo journalctl -u aquacore-relays.service -f` to confirm a real 10-second ON/OFF cycle. Wait 28 seconds from request before saving calibration (covers the queue window and pump runtime).
5. Measure how many mL were collected. Enter that value in **Collected volume (ml)** and click **Save calibration** within 15 minutes of the request.
6. AquaCore stores `ml_per_second = measured_ml / 10`. Set **Daily dose (ml)**, then do an independent short test into a measuring cup and verify delivery before routing fertilizer into the aquarium.

Example: 20 mL in 10 seconds = 2 mL/s; a 6 mL dose runs for 3 seconds.

Manual **Dose now** and automatic daily dosing both convert mL to seconds using the saved calibration. The runtime must be between 0.25 and 60 seconds; doses over 100 mL are rejected. A test pulse is always 10 seconds. Manual dosing is an **extra** dose; cooldown is 2 minutes across manual and calibration requests. If the pump, tubing, liquid viscosity, reservoir height or power supply changes, recalibrate. Volume accuracy depends on pump/tube priming and real-world flow. Do not use this as a safety-critical dosing system; add physical safeguards against siphoning and unexpected output.

## Live pump calibration progress bar (relay-worker status)

The Settings page displays **Waiting for relay worker** (indeterminate) when a calibration request is queued, an animated **0–100% / 10-second** progress bar after the relay worker writes the running state and activates its GPIO output, and **Completed** only after the relay worker has requested relay OFF. A status result is not physical proof that liquid was delivered. Interrupted, skipped, failed or unconfirmed pulses never count as calibration.

**Upgrade existing installations** (requires the earlier `fertilizer_pump.sql`, `fertilizer_manual.sql`, and `fertilizer_ml.sql` migrations):
```bash
sudo systemctl stop aquacore.service aquacore-relays.service
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_progress.sql
sudo mariadb _AquaCore_ -e 'SELECT pulse_state,pulse_kind,pulse_duration_seconds FROM fertilizer_pump WHERE id=1;'
sudo systemctl start aquacore.service aquacore-relays.service
sudo journalctl -u aquacore-relays.service -n 30 --no-pager
```

**Why Manual dose is unavailable:** calibration must have been saved (`ml_per_second` exists) and `dose_ml` must be greater than 0; an admin login is required. The button is also briefly blocked during the cooldown and while a pending manual request is being processed. You can use **Run test** without a prior calibration. Saving a new daily dose automatically refreshes the manual switch once the save request completes.

The new progress endpoint is `GET /api/fertilizer/status` (login required), using DB-server timestamps and relay worker states. The bar is not started when HTTP merely accepts a queued request. The flow-calibration Save button requires a completed, unused test recorded by the worker. The progress UI can reconnect after reloading the page within the calibration validation window.

## Compact fertilizer calibration window (Nov 2026)

Under **Settings → Equipment & lighting → Fertilizer pump**, there is now **one** fertilizer dosing row, styled like the other devices. Click **Calibration** beside the fertilizer name to open a compact modal. The separate pump-calibration device row has been removed.

In the window:
1. Prime the pump; route water to a graduated measuring cup **outside the aquarium**.
2. Select **Test duration** (2–60 whole seconds; 10 seconds is the suggested default).
3. Click **Run test**. The bar waits until the relay worker reports GPIO activation, counts the selected duration, and reaches 100% only after the worker records the OFF command.
4. Enter **Collected volume (ml)**, then **Save calibration**. The backend calculates `ml_per_second = measured_ml / actual_completed_pulse_duration_seconds` from the database record, not from a client guess.
5. Validate with a second measured dose before attaching the aquarium fertilizer feed.

Previously queued or stale tests cannot be saved and are not automatically displayed when reopening the modal. A failed/stale test means the relay worker likely did not confirm that pulse: check `sudo systemctl status aquacore-relays.service` and `sudo journalctl -u aquacore-relays.service -n 60 --no-pager`.

This user-interface/calibration calculation update uses **existing** `fertilizer_pump` columns and requires **no additional SQL migration**, provided that `fertilizer_progress.sql` has already been applied.

**Update**:
```bash
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo systemctl restart aquacore.service
```
If relay worker code is also behind the revision adding pump progress, restart `aquacore-relays.service` after ensuring its database migration is applied.

## Manual fertilizer pump ON/OFF (max 30 seconds) and calibration progress

The **Manual dose** switch is now a manual pump ON/OFF control, independent of any saved pump calibration and of the configured daily dose. **It controls time, not measured mL.** As an administrator, switch ON to request a manually timed pump run; switch OFF to request early shutdown. The relay worker automatically turns the pump OFF after **30 seconds maximum** even if the browser disconnects. Both requests require authenticated, CSRF-protected API calls; only the existing `aquacore-relays.service` commands GPIO 230.

When starting with an uncalibrated pump, collect into a measured container **outside the aquarium**. Do not interpret the manual switch as a calibrated fertilizer dose. A manual start uses the same 120-second minimum interval between starts as other pump requests, and cannot overlap a calibration test. The switch remains ON while the worker reports the manual pulse queued/running; switching OFF sends a stop request, with worker acknowledgment expected within its normal 1-second polling loop. If the relay service is down, a manual request can expire without activating.

The calibration popup displays an indeterminate bar for queued requests and an increasing 0–99% bar only after the relay service has recorded the pump ON command. It shows 100% and unlocks **Save calibration** only when the relay service records the OFF command and the measured volume has been entered. **Stale** means the relay worker did not confirm a run; no flow rate can safely be saved. If a request is stale, confirm the worker was restarted after applying `fertilizer_progress.sql` and inspect:
```bash
sudo systemctl status aquacore-relays.service --no-pager
sudo journalctl -u aquacore-relays.service -n 80 --no-pager
sudo mariadb _AquaCore_ -e "SELECT manual_request_id,manual_processed_id,manual_kind,pulse_kind,pulse_state,pulse_started_at,pulse_finished_at FROM fertilizer_pump WHERE id=1;"
```

**Deployment:** This update uses existing progress-state columns: no *new* migration is necessary if `fertilizer_progress.sql` was applied earlier. Restart both the web service and relay worker to activate the new manual ON/OFF endpoints and relay logic:
```bash
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo systemctl restart aquacore.service aquacore-relays.service
```


## Water temperature (ADS1115 A1 NTC) and calibrated pH (ADS1115 A0)

### Current AquaCore wiring: 5 V analog system, NTC not yet installed

PH-4502C and the ADS1115 breakout are supplied at **5 V**. The planned
temperature sensor is a two-wire waterproof **10 kΩ B3950 NTC** with a
separate fixed **10 kΩ pull-up resistor** to **5 V**:

```text
                  +5.0 V
                     |
                  fixed 10 kΩ
                     |
ADS1115 A1 ----------+----- NTC 10 kΩ B3950 ---- common GND
ADS1115 VDD <--------+5 V (power rail, not the A1 junction)
ADS1115 GND <-------- common GND
PH-4502C PO --------> ADS1115 A0
TDS analog output --> ADS1115 A3
```

At 25°C, the 10 kΩ NTC and 10 kΩ fixed resistor produce about **2.50 V**
at A1. The NTC is nonpolarized. **Do not enable A1 until the hardware
is physically installed**, and remove any previous PH-4502C T1/T2 signal
from A1. The supply in AquaCore's NTC conversion is **5.0 V**, sourced
from MariaDB.

**Important:** 5 V power on ADS1115 does not imply its SDA/SCL lines can
safely connect directly to Orange Pi Zero 2W 3.3 V GPIO. Some ADS1115
breakouts pull the I²C lines up to 5 V. Verify the actual breakout's pull-up
network and use a suitable bidirectional I²C level shifter if needed.
**Never allow 5 V on Orange Pi 3.3 V GPIO.** The current ADC PGA is ±4.096 V;
an A1/A0/A3 input can saturate above +4.096 V despite the ADC's 5 V VDD.

### Temperature data and three-buffer pH calibration

The `aquacore-tds.service` collector writes TDS, optional NTC water
temperature, and calibrated pH into the existing `data` table. pH uses
saved 4.01 / 6.86 / 9.18 reference voltages and, only after temperature
calibration, optional Nernst slope compensation from A1. When A1 is disabled
or disconnected, it does not invent a temperature from the TDS fallback.
The existing TDS multiplier is provisional until checked with a standard.

**NTC configuration is stored in the `sensor_calibration` MariaDB table.**
Do not set `NTC_ENABLED` or `NTC_SUPPLY_V` in the web service environment.

New and existing installations must add the DB columns before deploying
the matching web and collector changes:

```bash
sudo mariadb-dump _AquaCore_ > ~/aquacore-before-ntc-db.sql
sudo systemctl stop aquacore.service aquacore-tds.service
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/ntc_settings_migration.sql
sudo systemctl start aquacore.service aquacore-tds.service
sudo mariadb _AquaCore_ -e \
  'SELECT ntc_enabled,ntc_supply_v FROM sensor_calibration WHERE id=1;'
```

The migration is non-destructive. `ntc_enabled=0` (OFF) and
`ntc_supply_v=5.0` (V) are the defaults. When your NTC and fixed resistor
arrive, wire them with power disconnected, then go to **Settings →
Sensor Calibration → Temperature**, select **Enable A1 NTC**, confirm
**5.00 V**, and click **Save A1 hardware settings**. Calibrate A1 against
a separate thermometer before trusting its readings.

The temperature sensor can also be used while calibrating pH **only if
the pH and temperature probes are immersed together in the same buffer**.
Otherwise enter each buffer's measured temperature manually.

Read-only ADC check after wiring:

```bash
sudo -u aquacore -g i2c /opt/aquacore/.venv/bin/python \
  /opt/aquacore/sensorstest.py --bus 2 --all-channels --ntc --ntc-supply 5.0 --once
```

See [the complete three-buffer calibration and wiring guide](PH_THREE_BUFFER.md)
for the workflow and temperature safety constraints.

## Sensor calibration dialog and active-low water leak Telegram alarm (November 2026)

### Apply SQL migration before restarting the sensor collector or web process

```bash
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/sensor_calibration.sql
sudo mariadb _AquaCore_ -e "SELECT * FROM sensor_calibration;"
sudo systemctl restart aquacore.service aquacore-tds.service
```

In **Settings → Sensor calibration → Calibrate sensors**, an admin can capture averaged, stability-checked ADS1115 A1 and A0 readings, then explicitly save. A reading must be captured within 15 minutes before saving; unsteady or ADC-saturated signals are rejected. Pump operations are unaffected.

**Temperature:** The A1 NTC divider uses a **5 V fixed 10 kΩ pull-up** and NTC to common ground. Until it is installed, leave `sensor_calibration.ntc_enabled=0`. Enable the 5.0 V supply settings through the Temperature tab after wiring, then capture A1 in the same water as an independent thermometer, enter the measured °C (5–40°C), and save. The offset is bounded to ±5°C and stored in `sensor_calibration.temp_offset_c`.

**pH:** Place the probe in certified pH 7.00 buffer and capture A0 after stabilization, rinse, place in certified pH 4.00 buffer and capture again, check the certification acknowledgement and save. The collector automatically uses the saved `ph7_voltage` and `ph4_voltage` from `sensor_calibration` for new data rows. Drinking water, homemade vinegar dilutions and 5% vinegar are **not** certified calibration buffers. No pH will be reported unless valid reference voltages are stored. The existing pH ADC wiring is not modified in this update. Calibration cannot fix unsafe 5V-to-3.3V I2C pull-up or A0 overvoltage: **check actual signals independently**.

### Water alarm wiring — physical header pin 35 / PI2 / line 258

The Orange Pi Zero 2W maps physical header **pin 35 to PI2**, SoC GPIO **258**, expected libgpiod offset **258 on gpiochip1** in this installation. Confirm locally using `gpioinfo gpiochip1 | grep -E 'line +258:'`.

```text
          WATER LEAK SENSOR MODULE                 ORANGE PI ZERO 2W
          ------------------------                ------------------
          Digital OUT (DRY = 3.3V)  ------------>  PI2 physical pin 35
          Digital OUT (WET = 0V)    -- same wire --
          GND                      ------------>  GND physical pin 39 (or 34)
          Sensor power             ------------>  rated supply, per its datasheet

          IMPORTANT: Output on pin 35 must NEVER exceed 3.3V.
```

If your sensor is an **open-collector/open-drain** type, the monitor requests the SoC internal pull-up; an external 4.7k–10k pull-up to **3.3V** may be needed for stable readings. Never pull it up to 5V. If its digital output is 5V, use a suitable level shifter or divider *before* connection. Verify DRY=HIGH and WET=LOW with a meter or `gpioget` first.

The standalone `water_alarm.py` samples the input once per second, requires 3 stable readings, sends a **WET alert** via existing `BOT_TOKEN` to existing Telegram owner `MyTGaccount`, sends a **DRY recovery** after a previously delivered alarm, and repeats unresolved WET once per hour. Failed Telegram sends are retried every 30 seconds. Note: on process restart while already wet, a new initial alert is sent; power loss, network issues, and GPIO access failure prevent delivery. This is a supplemental monitoring alert, **not a safety-rated leak shutoff**.

### Install and enable alarm monitor

```bash
# Check permissions and free pin BEFORE enabling:
gpioinfo gpiochip1 | grep -E 'line +258:'
ls -l /dev/gpiochip1
id aquacore
# Ensure aquacore account can read the GPIO chip (existing udev/group setup).

sudo cp /opt/aquacore/deploy/systemd/aquacore-water-alarm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aquacore-water-alarm.service
sudo systemctl status aquacore-water-alarm.service --no-pager
sudo journalctl -u aquacore-water-alarm.service -f
```

With the alarm running, safely simulate DRY then WET using the actual 3.3V-compatible water-sensor output (do **not** tie the GPIO directly to the 3.3V power rail or output of an unverified 5V module). Expect one Telegram alarm on LOW and a recovery on HIGH; verify both physical states and Telegram delivery. Do not drive this input using `gpioset` while the alarm process owns the line.

`aquacore-water-alarm.service` is independent of `aquacore-telegram.service`; both use the same bot token safely because the alarm monitor only sends HTTP notifications and does not poll for Telegram updates.
