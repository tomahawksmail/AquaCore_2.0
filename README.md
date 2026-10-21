# AquaCore — MariaDB + Modern Web (Phase 1)

This is a *parallel* modernization of your original Flask web interface, using the **same table/column names** in your AquaCore SQL dump. It is NOT AquaCore 2.0's new backend and does not start GPIO, sensors, or Telegram. The web shows live MariaDB values, supports admin editing of documented `options` fields, and leaves your old automation in charge of hardware.

## 1. Create TEST database (MariaDB)

Do **not** import the SQL into your live database without backup. This script creates `_AquaCore_` if absent. To keep old and new separate when working against the same server, create another database name and edit the first 2 SQL lines plus `.env`.

```bash
mariadb -u root -p < create_test_database.sql
```

In MariaDB, create a dedicated account (substitute a long unique password):

```sql
CREATE USER IF NOT EXISTS 'aquacore_web'@'localhost' IDENTIFIED BY 'REPLACE_WITH_STRONG_DB_PASSWORD';
GRANT SELECT, INSERT, UPDATE ON `_AquaCore_`.* TO 'aquacore_web'@'localhost';
```

If using Windows to connect to MariaDB on a separate Orange Pi, use a narrowly scoped host/grant rather than `%`; configure a secured connection or SSH tunnel. If connecting with IP `127.0.0.1`, account host matching varies; create a matching `'aquacore_web'@'127.0.0.1'` or use localhost appropriately.

## 2. PyCharm / Windows test

Copy `.env.example` to `.env`, set `DB_PASSWORD`, `AQUACORE_ADMIN_PASSWORD` and generate `SECRET_KEY` with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Create a virtual environment and install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m flask --app app set-password
.\.venv\Scripts\python app.py
```

Open `http://127.0.0.1:5001`. PyCharm run configuration: **Script path** = `app.py`; working directory = project root. No relative-package imports.

This web version REQUIRES a modern hashed password; old MD5 hashes from your SQL dump won't log in. Reset using `set-password`. The original app keeps its previous authentication database behavior (do not use an old original app's MD5 login exposed publicly).

## 3. Pages

- `/aquarium`: overview, measurement table, read-only equipment flags, refreshes recent metric cards every 15 s.
- `/options`: range-validated water thresholds and original scheduling fields. Updates only columns that exist in original SQL.
- `/core_dashboard`: readings from `psutil` database table.
- `/loging`: event history.

## 4. Compatibility cautions

- The supplied SQL dump defines `RedL` and `BlueL`; existing `main.py` instead refers to `PlantL` in several settings routes. The redesign displays **RedL and BlueL** based on actual SQL and does not change original controller behavior.
- Your SQL dump lacks an `a_status` table, despite references in `functions.py` and `main.py`. Therefore this phase does not edit automatic mode flags. Resolve schema differences from the *actual Orange Pi database* before exposing these controls.
- The app intentionally does NOT expose arbitrary GPIO writes or a terminal. Equipment statuses are database flags, not physical relay verification.
- The original exported data includes historical logs and legacy password hashes. The clean TEST DB contains only table definitions and default options/status; no legacy users or historical data.
- Run the web app behind HTTPS/authenticated reverse proxy before exposing beyond your LAN. Use `COOKIE_SECURE=true` only with HTTPS. The app's built-in development server is for local testing.
- Existing main.py imports GPIO indirectly via its application, so do NOT use it for PyCharm testing. Run this standalone `app.py` instead.

## 5. Next step

Validate against your real MariaDB schema (`SHOW CREATE TABLE options; SHOW CREATE TABLE status; SHOW TABLES;`) before combining the new UI with the old controller. Backup database first. Then we can update the existing project incrementally without replacing its control logic.

## Historical charts (Phase 1.1)

The aquarium overview now includes **temperature, pH and TDS** charts with 24h / 7d / 30d / 90d selectors. Data comes from the existing `data` table via the authenticated `GET /api/history?period=24h` endpoint. MariaDB performs time-bucket aggregation (up to ~300 chart points per series), so it does not need to send the full raw history to a phone. Missing sensor readings are not filled with invented values. Charts update every minute while the tab is visible. They use local SVG/JavaScript (no CDN or additional pip dependencies), and they adapt to screen width.

**Update an existing installation:** replace `app.py`, `templates/dashboard.html`, and `static/style.css`, and add `static/charts.js`. No database migration is needed. Restart Flask. Testing requires a running MariaDB with real measurements.
