# Orange Pi relay controller

The modern AquaCore web app updates `status` in MariaDB. `scheduler.py` computes scheduled states and temporary manual overrides. `relay_controller.py` is the **only** component that should drive the GPIO output pins. Run each as a separate service/process, with exactly one instance of each.

## Six relay connections (Orange Pi Zero 2W)

Wiring is in the same order as AquaCore Settings. Physical header numbers and SoC GPIO numbers are different: this controller uses `gpio -g` and SoC GPIO numbers.

| AquaCore device | Database field | Physical pin | Port | SoC GPIO |
|---|---|---:|---|---:|
| CO₂ | `co2_status` | 18 | PH4 | 228 |
| Oxygen | `o2_status` | 22 | PI6 | 262 |
| UV sterilizer | `UV_status` | 24 | PH5 | 229 |
| Main light | `MasterL_status` | 26 | PH9 | 233 |
| Backlight | `Backlight_status` | 37 | PI16 | 272 |
| Plant light | `PlantL_status` | 36 | PC12 | 76 |

Active-low relay-module logic preserved from your previous code: `checked => LOW (0) => ON`; `unchecked => HIGH (1) => OFF`. Confirm your module really follows this and is electrically compatible with 3.3 V logic. Some 5 V relay boards need appropriate transistor/level-shifter drivers; Orange Pi GPIO must never power relay coils directly.

**Warning:** Configuring a GPIO as output can momentarily energize an active-low module. Test with loads disconnected and arrange hardware pull-ups/enable gating for fail-safe startup. Confirm `gpio readall` reports physical pins and SoC names exactly as above. Make sure none of these pins are reserved by SPI/I2C/UART overlays.

Heater and removed Moonlight/Projector are deliberately excluded.

## Second relay module: four reserved channels

| Channel | Physical header | Port | SoC GPIO | Status |
|---|---:|---|---:|---|
| Spare 1 | 29 | PI0 | 256 | Reserved, inactive |
| Spare 2 | 23 | PH6 | 230 | Reserved, inactive |
| Spare 3 | 21 | PH8 | 232 | Reserved, inactive |
| Spare 4 | 19 | PH7 | 231 | Reserved, inactive |

These are listed in `SPARE_PIN_MAP` but deliberately excluded from the live `PIN_MAP`. The controller does not configure or drive these GPIO pins, and there are no database status fields for them.

**SPI conflict:** Physical pins 19, 21, and 23 have SPI alternate functions. Inspect `gpio readall` and enabled device-tree overlays before using them as outputs. No loads should be connected to the second module during mapping and polarity checks.

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
