# AquaCore 2.0 — clean installation with an empty database

The uploaded HeidiSQL export was **not a usable schema export**: it contained export metadata and “Data exporting was unselected” but no `CREATE TABLE` statements. The accompanying `deploy/sql/aquacore_empty_bootstrap.sql` is rebuilt from the project's base database definitions and current migrations.

This bootstrap provides **tables plus only the four required configuration rows**. There are **no existing logins**, passwords, Wi-Fi credentials, Telegram users, history, or measurements. It is intended for a **fresh, isolated installation**, not for replacing a running aquarium's database.

## Included schema

Core tables: `data`, `loging`, `manual_overrides`, `options`, `psutil`, `status`, `telegram_users`, `users`, `WiFi`.

Current additions: `fertilizer_pump2`, `sensor_calibration`, both pumps' schedule/calibration and bounded pulse columns, and CPU cooler threshold columns. Network/disk counters use 64-bit `BIGINT UNSIGNED` to avoid overflow.

## First-time install

**Do not run on your production `_AquaCore_` database.** The following steps assume a new/empty MariaDB server or a separate development instance, and code already cloned to `/opt/aquacore`.

1. Keep relays and external aquarium loads physically disconnected and ensure independent cooling for the Orange Pi.
2. Install MariaDB; configure the system and Python venv following `deploy/NATIVE_ARMBIAN.md`.
3. Bootstrap a fresh empty database:

```bash
sudo mariadb < /opt/aquacore/deploy/sql/aquacore_empty_bootstrap.sql
```

4. Create a least-privileged database account and configure `/etc/aquacore/web.env` with your *own* new credentials. Do not copy passwords or keys from other installations. Example:

```sql
CREATE USER 'aquacore_web'@'localhost' IDENTIFIED BY 'SET_A_STRONG_UNIQUE_SECRET';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`_AquaCore_\`.* TO 'aquacore_web'@'localhost';
```

5. Create your first administrator with AquaCore's existing password command. Use a password manager; do not paste production secrets into a public issue:

```bash
sudo bash -c '
  set -a
  . /etc/aquacore/web.env
  set +a
  export AQUACORE_ADMIN_USER=admin
  read -r -s -p "New admin password (12+ chars): " AQUACORE_ADMIN_PASSWORD
  echo
  export AQUACORE_ADMIN_PASSWORD
  cd /opt/aquacore
  .venv/bin/python -m flask --app app set-password
  unset AQUACORE_ADMIN_PASSWORD
'
```

6. Start **web only** for initial review; configure sensors, relay wiring, schedule and safety controls before enabling any hardware worker:

```bash
sudo systemctl start aquacore.service
sudo systemctl is-active aquacore.service
```

**Do not start** `aquacore-relays.service` before confirming the actual pin map, safe OFF states and external interlocks. Pump 1's default enable flag is 1; set `PUMP1_ENABLED=0` and `PUMP2_ENABLED=0` in `/etc/aquacore/web.env` during initial wiring verification.

## Validation

```bash
sudo mariadb _AquaCore_ -e 'SHOW TABLES;'
sudo mariadb _AquaCore_ -e 'SELECT fertilizer_dose_ml,fertilizer_weekdays,cooler_on_c,cooler_off_c FROM options;'
sudo mariadb _AquaCore_ -e 'SELECT fertilizer_dose_ml,fertilizer_weekdays FROM fertilizer_pump2;'
sudo mariadb _AquaCore_ -e 'SELECT COUNT(*) AS users FROM users; SELECT COUNT(*) AS sensor_rows FROM data;'
```

Expected: one row each in `options`, `status`, `fertilizer_pump2`, `sensor_calibration`; zero users/measurements; each pump's daily dose is 0 mL; cooler thresholds default to 70/65°C.

This file is designed for MariaDB 11.x. Test against a fresh MariaDB instance before production deployment. For application or database updates on an existing installation, use targeted migrations and a backup instead.
