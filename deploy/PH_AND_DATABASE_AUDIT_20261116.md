# pH 9.87 after A1 temperature wiring — diagnostics and safe DB cleanup

This change set targets the Orange Pi Zero 2W / ADS1115 (I²C-2, 0x48):
A0=pH, A1=3.3 V NTC divider, A3=TDS. The working A1 sensor is not
evidence of an accurate pH calibration.

## Why an unexpected pH value appears

The collector's precedence is:
1. `ph_provisional_enabled=1`: **unverified** operator anchor
   A0=2.40 V → pH≈7; saved three-buffer curve and Nernst compensation ignored.
2. Otherwise, valid three-buffer references plus A1 temperature + calibration
   buffer temperatures → 3-point Nernst slope correction.
3. Otherwise, valid three-buffer references → uncompensated 3-point curve.
4. Otherwise, a valid legacy pH 7/4 pair → legacy curve.

The old 3-point references may have been captured at different cable/amplifier
conditions from today's A0 voltage. Switching on A1 allows path 2 to activate;
that does not make an outdated pH electrode calibration trustworthy.
A reported pH 9.87 alone cannot establish the actual aquarium pH.

**Do not use provisional pH to drive CO₂, acid/base dosing, or safety actions.**

### Verify the running Orange Pi (read-only)

```bash
cd /opt/aquacore
git rev-parse --short HEAD
sudo mariadb _AquaCore_ -e "
SELECT ph_provisional_enabled, ph_provisional_neutral_v, ph_factor,
       ph401_voltage,ph686_voltage,ph918_voltage,
       ph401_reference,ph686_reference,ph918_reference,
       ph401_temp_c,ph686_temp_c,ph918_temp_c,
       ntc_enabled,ntc_supply_v,temp_updated_at,temp_factor,temp_offset_c
FROM sensor_calibration WHERE id=1\G"
sudo journalctl -u aquacore-tds.service -n 30 --no-pager
```

Look for `pH mode=PROVISIONAL_UNVERIFIED`, `THREE_BUFFER_ATC`,
`THREE_BUFFER_NO_ATC`, or `LEGACY_TWO_BUFFER`, as well as raw A0 voltage.
These modes appear in collector logs after this change is deployed.

If `ph_provisional_enabled=0`, the current collector intentionally uses
saved buffer calibration. That can explain a large discrepancy after A1
becomes active.

### Restore the operator-requested 2.40 V → pH 7 temporary display

Prefer **Options → Sensor calibration → pH → Temporary unverified pH
estimate**, enable it, enter `2.40` and save. The same change can be made
explicitly in the running MariaDB database:

```sql
UPDATE sensor_calibration
SET ph_provisional_enabled=1,
    ph_provisional_neutral_v=2.40,
    ph_provisional_started_at=NOW()
WHERE id=1 AND
      (ph_provisional_enabled<>1
       OR ph_provisional_neutral_v<>2.40
       OR ph_provisional_started_at IS NULL);
```

This does not erase saved calibration points. The collector loads settings
once per sampling cycle (normally every 30 seconds). With A0 about 2.40 V,
the output should be about 7.0 regardless of A1 temperature. **It is an
unverified estimate, not a confirmed water pH.** Use freshly prepared buffer
solutions and stable A0 measurements for a proper three-buffer calibration.

## Database audit

The current `data`, `sensor_calibration`, `options`,
`fertilizer_pump2`, `status` and `psutil` tables are still required.
The `WiFi` and legacy fields are retained pending confirmation that no
external setup scripts depend on them; pH 7/4 fields are still read by the
legacy calibration fallback. Do **not** delete them.

Two fresh-install schemas were missing the modern NTC/three-buffer/provisional
columns: `deploy/sql/clean_install.sql` and
`deploy/sql/aquacore_empty_bootstrap.sql`. They now match
`deploy/sql/sensor_calibration.sql`.

Eight legacy `psutil` columns are not written by `system_collector.py`
or read by the dashboard/Telegram integration:

```text
scpufreq_min, scpufreq_max, cpu_thermal_high, cpu_thermal_crit,
gpu_thermal_cur, gpu_thermal_high, gpu_thermal_crit, ve_thermal_cur
```

They are omitted from *new* installations. On an *existing* installation,
the optional maintenance SQL `deploy/sql/cleanup_unused_db_fields.sql`
drops an allowlisted column only when all existing values are NULL/zero.
If it contains any nonzero data it is left alone for investigation.

The old scheduler wrote fake `temp=0,ph=0,tds=0` and all-zero `psutil`
rows when collectors were offline. This change stops generating those
rows. The dashboard marks live metrics unavailable after a 90-second gap,
preserves genuine history and excludes all-zero sensor samples from new
history responses.

### Optional cleanup of an existing database

**Never run the fresh-install SQL files on a live tank.** Review the
cleanup SQL carefully; it deletes legacy synthetic zero rows and conditionally
drops the eight unused metrics. It does not delete real sensor readings,
pH calibration values, schedules or pump state.

After ensuring equipment stays in a safe state, stop web and writers,
and take a verified backup before the cleanup:

```bash
sudo systemctl stop aquacore.service aquacore-scheduler.service \
  aquacore-tds.service aquacore-system.service
sudo mariadb-dump --single-transaction --routines --triggers _AquaCore_ \
  > ~/aquacore-before-cleanup-$(date +%Y%m%d-%H%M%S).sql

# Inspect and verify the backup before applying any destructive SQL.
less deploy/sql/cleanup_unused_db_fields.sql
sudo mariadb < deploy/sql/cleanup_unused_db_fields.sql
```

After any new code is installed and the schema changes are reviewed, start
the same services and confirm correct system/temperature/TDS metrics and
the pH mode reported in the collector journal. Verify existing hardware
relay state separately; DB entries do not prove electrical OFF.
