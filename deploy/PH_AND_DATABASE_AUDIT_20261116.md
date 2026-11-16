# AquaCore 2.0 — Two-buffer pH and A1 temperature (November 16, 2026)

## Hardware and conversion

- ADS1115 I²C bus 2, address 0x48.
- A0: pH electrode interface output. A1: 10k NTC B3950 and 10k fixed
  pull-up from **3.3 V** to A1, NTC from A1 to common GND.
- A3: TDS sensor. The A1 thermistor must be configured **and calibrated**
  before AquaCore writes pH or temperature-corrected TDS.
- pH electrode reference pairs: 2.540 V → pH 6.86, 3.040 V → pH 4.01.
  Reference liquid temperatures are **assumed to be 25.0°C** because
  their actual recorded temperatures were not supplied. If they differ,
  recapture both buffers in the calibration dialog with A1 and A0 in the
  same solution, or use a reference thermometer in the manual field.

At 25°C: `pH = 6.86 + (V_A0 - 2.54) × (4.01-6.86)/(3.04-2.54)`.
For A0=2.40 V, this predicts pH approximately **7.658** at 25°C.
This is a *two-buffer calibration model*, not confirmation of aquarium pH.
The saved buffer temperatures and A1 water temperature correct the slope
in Kelvin using the Nernst approximation; they never transform aquarium
chemistry into a fictional fixed temperature. Verify independently before
using pH for any automated CO₂/dosing decisions.

## Existing installation, exact order

1. Ensure physical pumps/relays/CO₂ are in a safe OFF state. Back up your
   running MariaDB database and verify the backup can be read.
2. Stop writers and web services. Do not stop electrical safety controls
   unless you have a verified independent cooling/protection arrangement.
3. Update the repository to this PR's code **without starting services**.
4. Run the one-time schema migration from the updated checkout:
   `sudo mariadb < deploy/sql/ph_two_buffer_ntc_migration.sql`.
   It seeds the two voltages above, labels earlier pH readings as old
   calibration history, and drops 11 unused calibration columns. It
   preserves the A1 enable flag, NTC offset/factor, TDS factor and real
   temperature/TDS history.
5. Install the updated systemd collector unit: `sudo cp
   /opt/aquacore/deploy/systemd/aquacore-tds.service /etc/systemd/system/`;
   run `sudo systemctl daemon-reload`. The legacy `--temperature 22`
   flag is no longer supported.
6. Start the updated web + sensor collector and inspect
   `sudo journalctl -u aquacore-tds.service -n 30 --no-pager`.
   New log mode is `TWO_BUFFER_A1_ATC`. Confirm pH near 6.86 at A0
   2.54 V when water is around the assumed calibration temperature.
7. Only after validating new code and backups, consider the **optional**
   `deploy/sql/cleanup_unused_db_fields.sql`. It clears obsolete old
   pH cells, fake all-zero outage records and eight unused host metric
   columns only if they contain no nonzero values. This file never runs
   automatically. Review candidate counts before executing.

Example backup (run in a protected folder; no secrets in the repo):

```bash
sudo mariadb-dump --single-transaction --routines --triggers _AquaCore_ \
  > ~/aquacore-backup-$(date +%Y%m%d-%H%M%S).sql
```

**Do not import `clean_install.sql` or `aquacore_empty_bootstrap.sql`
on an existing database.** They are solely fresh-install schemas.

## Calibration dialog

Settings → Sensor calibration → Temperature: enable A1, confirm the
divider uses 3.3 V and save a glass thermometer reference.

Settings → Sensor calibration → pH: current saved two-buffer voltages
are displayed. To recapture, place both A0 and A1 probes together in
pH 6.86 buffer, select “Use A1 NTC temperature”, wait for stable voltage,
Capture 6.86, then rinse and repeat for pH 4.01. Save both buffers.
If A1 remains in the aquarium, instead manually enter the **actual**
calibration-liquid temperatures; do not use aquarium water temperature
to label a separate calibration glass.

## Telegram chart vs web

Web `/api/history?period=24h` and Telegram `📈 Aquarium chart` call
the same `water_history.history_sql("24h")` aggregation and use the
same min/max limits, pH calibration cutoff and time buckets.
Both display lines for temperature/pH/TDS with matching metric colors,
permitted-range shading and gaps for sensor outages. The web is an
interactive SVG; Telegram is a 24-hour PNG, so interaction and font
metrics differ. Telegram System chart retains its separate CPU/RAM
rendering.

## Database retained

Required live tables: `data`, `sensor_calibration`, `options`,
`status`, `psutil`, `fertilizer_pump2`, `users`,
`telegram_users`, `loging`, `manual_overrides`. `WiFi` is retained
pending an audit of any external Orange Pi AP setup script; deleting a
table based only on this repo would be unsafe. Active calibration columns
are precisely the ones in `deploy/sql/sensor_calibration.sql`.

No operations on the live device have been performed in this PR.
