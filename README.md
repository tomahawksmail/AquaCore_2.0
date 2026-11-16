# AquaCore 2.0 — aquarium automation

Flask/MariaDB web dashboard and Orange Pi Zero 2W controller with separate
systemd workers for ADS1115 water sensors, equipment schedules, relay outputs,
water-leak detection, and Telegram bot. This is a live hardware automation
project: **do not run production relay workers in a test environment**.

## Sensor channels

- A0: analog pH electrode; 2.540 V / pH 6.86 and 3.040 V / pH 4.01.
- A1: 10k B3950 NTC with 10k fixed resistor to 3.3V.
- A3: analog TDS probe and user-calibrated TDS multiplier.
- ADS1115 I²C bus 2, address 0x48; 5-sample median pH collector.
- Calibrated A1 temperature is required for pH and TDS; there is no
  provisional pH mode or default 22°C substitute. Temperature correction
  is a Nernst slope approximation, not proof of aquarium pH accuracy.

The two reference solution temperatures are initially assumed 25°C until
recaptured with measured buffer temperature. At 25°C A0=2.40V predicts
pH≈7.66, not exactly pH 7.00.

## Charts

Web dashboard `/api/history?period=24h` and Telegram
`📈 Aquarium chart` use the same `water_history.history_sql`
24-hour aggregate, acceptable-range limits, missing-sample gaps and
pH calibration cutoff. The web visual is interactive SVG; Telegram sends
a PNG with the same data, series colors and range shading. System metrics
and pump charts are separate.

## Quick deployment references

- [Native Armbian services and GPIO guidance](deploy/NATIVE_ARMBIAN.md)
- [Two-buffer sensor conversion, migration and database audit](deploy/PH_AND_DATABASE_AUDIT_20261116.md)
- [Telegram setup and access control](deploy/TELEGRAM.md)
- [Fresh MariaDB installation only](deploy/EMPTY_DATABASE_RELEASE.md)
- [Hardware health checks](deploy/check_health.sh)

### Existing MariaDB installations

Never use `deploy/sql/clean_install.sql` or
`deploy/sql/aquacore_empty_bootstrap.sql` against a running aquarium.
They are **fresh-install only**.

For the new two-point model, stop relevant services safely, back up
`_AquaCore_`, update source and apply
`deploy/sql/ph_two_buffer_ntc_migration.sql` **once** before restarting
services. This intentionally replaces legacy provisional/three-buffer
calibration columns without touching configured A1 calibration offset or
TDS multiplier. Use `deploy/sql/cleanup_unused_db_fields.sql` only
after review and a verified backup to remove old-curve pH cells, artificial
all-zero history rows and eight unused host metric columns.

Fresh installation and live GPIO/I²C verification are not covered by
the offline GitHub Actions suite. All physical outputs must be verified
safe before enabling any workers.

## Offline regression checks

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
for file in static/*.js; do node --check "$file"; done
```

Do not commit `.env`, passwords, API tokens, or production database dumps.
