# AquaCore relay controller — Orange Pi Zero 2W

The running controller is `relay_controller.py`, owned by the systemd unit `aquacore-relays.service`. It uses **libgpiod v2** and `/dev/gpiochip1`. Do not use old `gpio -g` / `gpio readall` examples to infer the active mapping.

## Current GPIO wiring (November 2026)

| Device | Status field | SoC pin | gpiochip1 offset | Physical header |
| --- | --- | --- | ---: | ---: |
| CO₂ | `co2_status` | PI0 | 256 | 29 |
| Oxygen | `o2_status` | PI6 | 262 | 22 |
| Main light | `MasterL_status` | PH5 | 229 | 24 |
| Backlight | `Backlight_status` | PI16 | 272 | 37 |
| Plant light | `PlantL_status` | PC12 | 76 | 36 |
| UV sterilizer | `UV_status` | PH4 | 228 | 18 |
| Pump 1 | `fertilizer_pump_status` | PH6 | 230 | 23 |
| Pump 2 | `fertilizer_pump2_status` | PH7 | 231 | 19 |
| CPU cooler | internal CPU thermal logic | PH8 | 232 | 21 |
| Spare (uncontrolled) | none | PH9 | 233 | 26 |

CO₂ and UV physical outputs were swapped: **CO₂ is PI0 / 256 / physical 29**; **UV is PH4 / 228 / physical 18**. Pump 1 is controlled by `PUMP1_ENABLED` (default 1); Pump 2 by `PUMP2_ENABLED` (default 0). These flags are read from `/etc/aquacore/web.env` by the systemd services.

Relay inputs are **active LOW**: HIGH is requested OFF (`Value.ACTIVE` in this libgpiod configuration without `active_low=True`), LOW is requested ON (`Value.INACTIVE`). Do not connect relay coils or motors directly to Orange Pi GPIO. Verify voltage compatibility and arrange physical failsafe OFF bias; the kernel does *not* guarantee OFF after line release.

## Read-only inspection while AquaCore is running

```bash
systemctl is-active aquacore-relays.service
gpioinfo -c gpiochip1 256 262 229 272 76 228 230 231 232
sudo grep -E 'PH4|PI0|PI6|PH5|PI16|PC12|PH6|PH7|PH8' /sys/kernel/debug/pinctrl/300b000.pinctrl/pinmux-pins
sudo journalctl -u aquacore-relays.service -n 40 --no-pager
```

`gpioinfo` shows ownership, direction and (on supporting versions) configuration, **not a guaranteed actual voltage measurement**. `gpioget` may return “Device or resource busy” for lines held by AquaCore; don't stop the service merely to read a pin.

## Bounded manual relay click test (no aquarium/mains loads)

**Safety requirements:** Disconnect **every** controlled external load, including UV, CO₂ solenoid, pumps and lights. The relay service also controls the CPU cooling fan on PH8, so provide independent CPU cooling during testing and monitor CPU temperature. Check all relay outputs are electrically isolated and the board has stable OFF bias when GPIO is released. Only test the *relay input*, never directly energize a mains or aquarium load. Perform a one-channel test with an appropriate 3.3V-compatible relay module. If any prerequisite cannot be met, do not perform the manual test.

1. Confirm the active `relay_controller.py` mapping from the local checkout and stop the worker *after* loads are isolated:
   ```bash
   grep -E '"(co2_status|o2_status|MasterL_status|Backlight_status|PlantL_status|UV_status)"|PUMP(2)?_PIN|COOLER_PIN' /opt/aquacore/relay_controller.py
   sudo systemctl stop aquacore-relays.service
   ```
2. Run this single-purpose test. Change `LINE=256` to the mapped line you want to test. It requests **HIGH/OFF immediately**, then holds LOW/ON for **0.5 seconds**, then HIGH/OFF again. It is not suitable for the CPU cooler channel:
   ```bash
   cd /opt/aquacore
   sudo LINE=256 .venv/bin/python - <<'PY'
import os
import time
import gpiod
from gpiod.line import Direction, Value

line = int(os.environ["LINE"])
allowed = {256, 262, 229, 272, 76, 228, 230, 231}
if line not in allowed:
    raise SystemExit("Unknown or disallowed relay line")
with gpiod.request_lines(
    "/dev/gpiochip1",
    consumer="aquacore-manual-test",
    config={line: gpiod.LineSettings(
        direction=Direction.OUTPUT,
        output_value=Value.ACTIVE,  # physical HIGH = OFF
    )},
) as request:
    print(f"Line {line}: HIGH/OFF")
    time.sleep(1)
    try:
        print(f"Line {line}: LOW/ON for 0.5s")
        request.set_value(line, Value.INACTIVE)
        time.sleep(0.5)
    finally:
        request.set_value(line, Value.ACTIVE)  # physical HIGH = OFF
        print(f"Line {line}: HIGH/OFF")
        time.sleep(1)
print("Released GPIO; OFF state is not guaranteed after release")
PY
   ```
3. After safely restoring equipment connections and confirming valid schedules/states and fan operation, start the sole relay worker:
   ```bash
   sudo systemctl start aquacore-relays.service
   sudo systemctl is-active aquacore-relays.service
   sudo journalctl -u aquacore-relays.service -n 30 --no-pager
   ```

The worker may legitimately switch outputs ON at startup according to saved DB commands. Do not reconnect aquarium/mains loads until you have confirmed those commands and output polarity. Never run a manual `gpioset` process concurrently with the worker.

## Database scheduling versus physical state

`scheduler.py` computes status requests, and the relay worker drives GPIO. The database flags (`checked` or `unchecked`) indicate *commands*, not independent physical feedback. A GPIO/DB failure can leave a relay in its last state; use hardware interlocks for critical loads. Pump manual/calibration is handled by independent safeguarded APIs and the relay worker; do **not** toggle pump GPIO while those services are running.

## Legacy notes

Older `deploy/NATIVE_ARMBIAN.md` sections describe earlier relay maps and obsolete pump SQL migrations. The current source code and this document take precedence. Use the current `deploy/FERTILIZER_PUMP2.md` for the two pump wiring and enable flags.
