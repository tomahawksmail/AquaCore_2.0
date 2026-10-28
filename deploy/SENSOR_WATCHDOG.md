# AquaCore sensor-missing fallback

The web UI reads `data.temp`, `data.ph`, and `data.tds`; the original sensor-acquisition service is not included here.

Optional script: `sensor_watchdog.py`. It checks the latest timestamp in `data` using the **MariaDB server's time**. If no row has arrived for at least 120 seconds, it can append:

```sql
INSERT INTO `data` (`Datetime`, `temp`, `ph`, `tds`)
VALUES (NOW(), 0, 0, 0);
```

### Test (read-only by default)
```bash
cd /home/orangepi/AquaCore
.venv/bin/python sensor_watchdog.py --stale-seconds 120
```

### Enable (only after validation)
```bash
.venv/bin/python sensor_watchdog.py --apply --stale-seconds 120 --poll-seconds 15
```

Only one watchdog should run at a time; the script uses a MariaDB named lock for each check. It does not fabricate an initial row when `data` is empty. It will keep inserting one zero row after each subsequent 120-second gap as long as nothing new arrives. The regular sensor writer may continue inserting actual rows at any time.

**Safety considerations:** A numeric zero is *not* a valid temperature/pH/TDS sensor measurement, and is indistinguishable from a real zero in the current `data` schema. If any controller responds to `data.temp` or `data.ph`, treating fabricated zeros as real measurements can cause dangerous actions. Add a data-quality/status column or explicit stale flag before using readings for heater, CO₂, dosing, or other automation. The watchdog must not control relays.

If you want a zero inserted for each failed acquisition attempt instead of a database-staleness fallback, put fallback logic directly in the acquisition script when that script is available.
