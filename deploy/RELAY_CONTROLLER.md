# Orange Pi relay controller

The modern AquaCore web app updates `status` in MariaDB. `scheduler.py` computes scheduled states and temporary manual overrides. `relay_controller.py` is the **only** component that should drive the GPIO output pins. Run each as a separate service/process, with exactly one instance of each.

## Migrated relay channels

| DB field | Orange Pi `gpio` pin | Source |
|---|---:|---|
| `co2_status` | 19 | previous R2 wiring |
| `o2_status` | 14 | previous R2 wiring |
| `UV_status` | 12 | previous R2 wiring |
| `MasterL_status` | not confirmed | configure via env |
| `Backlight_status` | not confirmed | configure via env |
| `PlantL_status` | not confirmed | configure via env |

Old heater relay (11) is **not** managed. Removed Moonlight/Projector are not managed. Additional pins used by other modules are untouched. Pin numbering matches the existing `gpio` CLI, not Linux GPIO chip offsets. Outputs preserve active-low behavior: `checked => gpio write PIN down`; `unchecked => gpio write PIN up`.

## Install and safely test

1. STOP the old relay script/service first. Two controllers writing the same physical outputs can cause unexpected cycling.
2. Configure the existing `.env` (default path `/home/orangepi/AquaCore/.env`, or override `AQUACORE_ENV`). Database variables may use `HOST, USER, PASSWORD, DATABASE` or `DB_HOST, DB_USER, DB_PASSWORD, DB_NAME`.
3. Test the database status records and logic without touching GPIO:

```bash
cd /home/orangepi/AquaCore
.venv/bin/python relay_controller.py
```

4. Verify real GPIO command availability, pin mapping and polarity against the actual relay board. With relay loads safely isolated, start actual output mode:

```bash
.venv/bin/python relay_controller.py --apply
```

5. Only after confirming wiring, supply optional pin numbers in `.env`:

```ini
# Set ONLY after identifying the exact hardware wiring:
# AQUACORE_GPIO_MAINLIGHT=10
# AQUACORE_GPIO_BACKLIGHT=13
# AQUACORE_GPIO_PLANTLIGHT=15
```

The numbers above are **examples, not established hardware assignments**; the old R1/U9/U10 listing alone did not identify which light connects to which pin.

## Reliability notes

- The controller reads status by **column name**, not tuple position, and opens a fresh DB connection for each poll.
- The controller **never** writes to the database. Manual requests and scheduled requests remain in the web app and scheduler.
- The default is DRY RUN. `--apply` is required to actuate hardware.
- A database failure leaves outputs at their *last state*; it does **not** turn all equipment off. Consider independent thermal, electrical and CO2 safety interlocks and a watchdog before unattended operation.
- GPIO initialization via `gpio mode ... out` might momentarily change pin levels depending on hardware. Always test startup on isolated loads; startup must not be assumed fail-safe.
- If the process crashes while a relay is on, the physical output can remain on. The script is **not** a safety system.
- Pin 6 button, GPIO heater, U9, U10, and other unnamed outputs remain outside this worker because their complete functionality/wiring were not supplied.

### Run with scheduling

```bash
.venv/bin/python scheduler.py
# In a separate terminal:
.venv/bin/python relay_controller.py --apply
```

Use dedicated systemd services once manual verification is complete; do not launch the old relay loop simultaneously. Do not use Gunicorn to run GPIO processing.
