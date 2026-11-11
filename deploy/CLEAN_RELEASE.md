# AquaCore 2.0 — Clean-install database release candidate

This release package adds a **fresh-install-only** MariaDB schema at `deploy/sql/clean_install.sql`. It is derived from the historical table definitions and the current unified pump, sensor and cooler migrations. The user-provided `aquacore.sql` export contained **no schema or data**, so it cannot be imported as a bootstrap database.

## Contents

- 9 base tables: `data`, `loging`, `manual_overrides`, `options`, `psutil`, `status`, `telegram_users`, `users`, `WiFi`
- `fertilizer_pump2` and `sensor_calibration` added via the current schema migrations
- Current Bottle A and B dosing fields, and CPU cooler threshold fields
- `psutil` cumulative counters widened to `BIGINT UNSIGNED` to avoid collector overflow
- Empty sensor/system history, empty logs, empty users and WiFi table, no plaintext or hashed password
- A single `options` and `status` row required by the application, with **all equipment OFF**, no configured ON/OFF time, and **0 mL / no weekdays** for both pumps
- Sensor calibration default placeholder values; actual probes must be calibrated before use

## New installation only

**Never import this into your running AquaCore database.** Back up before any database changes and verify the target is a dedicated fresh database. The SQL assumes MariaDB 10.6+ and the database name `_AquaCore_`.

```bash
sudo mariadb < deploy/sql/clean_install.sql
```

No default login is included. Create administrator credentials securely by setting `AQUACORE_ADMIN_USER` and `AQUACORE_ADMIN_PASSWORD` in a restricted environment (never in Git), then:

```bash
cd /opt/aquacore
sudo -u aquacore /opt/aquacore/.venv/bin/python -m flask --app app set-password
```

Run this command within the same environment the web service uses (`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and admin variables). Protect `/etc/aquacore/web.env` with mode 600 and root ownership. Verify the new database has **one `options` row, one `status` row, one Bottle B row, and one sensor calibration row**, plus the newly created admin user.

Do not start `aquacore-relays.service` or `aquacore-scheduler.service` until the actual active-low relay wiring, GPIO mapping, thermostat/cooler, supply voltages, and control schedules are tested. The installer does not energize relays automatically.

## Verification

```sql
USE `_AquaCore_`;
SELECT COUNT(*) FROM options;
SELECT COUNT(*) FROM status;
SELECT COUNT(*) FROM fertilizer_pump2;
SELECT COUNT(*) FROM sensor_calibration;
SELECT COUNT(*) FROM data;
SELECT COUNT(*) FROM psutil;
SELECT COUNT(*) FROM users;
SELECT fertilizer_weekdays,fertilizer_dose_ml,fertilizer_ml_per_second FROM options;
SELECT fertilizer_weekdays,fertilizer_dose_ml,fertilizer_ml_per_second FROM fertilizer_pump2;
```

## Publishing

Once reviewed and merged into `master`, create a GitHub release tagged at the **merged commit**, with `deploy/sql/clean_install.sql` as its SQL asset. A pull request is not itself a published GitHub release.
