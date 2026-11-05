# AquaCore 2.0 — second fertilizer pump (Bottle B)

Adds a second independent dosing pump while keeping the original bottle and
relay unchanged.

| | Pump 1: Bottle A | Pump 2: Bottle B |
|---|---|---|
| Orange Pi Zero 2W physical header | 23 | 19 |
| GPIO name / gpiochip1 offset | PH6 / 230 | PH7 / 231 |
| Database storage | existing `options` fields | new `fertilizer_pump2` singleton |
| Pump status column | `status.fertilizer_pump_status` | `status.fertilizer_pump2_status` |
| Default time | existing value | 12:30 |
| Dose after installation | existing value | **0.00 mL** |
| Calibration after installation | existing value | **not calibrated** |
| Weekdays | existing value | all seven days (no dose until calibrated) |

**Important: pin 19 can be assigned to SPI.** The code labels PH7 as an unused
relay output, but that does not establish whether your physical wiring or
device-tree overlays make it usable. Verify this on the actual Orange Pi before
connecting the relay. PH9 / physical 26 remains spare.

## Safety

- Keep `PUMP2_ENABLED=0` (default) until the relay and pin mapping are verified.
  In that state the new relay line is **not requested**, and Pump 2 manual
  activation/calibration cannot be initiated from the web API.
- Orange Pi GPIO must not power motors or relay coils directly. Drive a suitable
  relay module with proper external supply and wiring, and confirm active-low
  polarity. GPIO LOW = ON, HIGH = OFF in this application.
- Disconnect the pump power/load while validating relay polarity and startup
  behavior. GPIO modes can transiently change at power-on.
- Each pump has its own independent <=60-second timed output pulse, <=30-second
  manual priming, request cooldown, scheduled run guard, and calibration.
- The database records commands to relays, **not actual liquid flow**.
  Use a measuring cup with water outside the aquarium for both pump calibrations.
- If the fertilizer concentrates should not mix, do not share delivery tubing
  and do not schedule simultaneous doses; use separate outlet locations.
- Never use this controller as the only protection against over-dosing.

## Install (once)

1. Review the PR, back up the MariaDB database, and merge into `master`.
2. Stop web and relay services before deployment:

   ```bash
   sudo systemctl stop aquacore.service aquacore-relays.service
   sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master
   sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_pump2_migration.sql
   ```

3. Keep `PUMP2_ENABLED=0` in `/etc/aquacore/web.env` initially (or omit it).
   Start services:

   ```bash
   sudo systemctl start aquacore.service aquacore-relays.service
   sudo systemctl status aquacore-relays.service
   ```

4. From the AquaCore web UI, go to **Settings → Pump 2 · Bottle B**.
   Its schedule and dose settings are separate from Pump 1.
5. With the load disconnected, verify PH7, relay module, polarity and a stable
   OFF state. Confirm no SPI overlay owns pin 19.
6. Only after hardware verification, add `PUMP2_ENABLED=1` to the shared
   `/etc/aquacore/web.env` and restart *both* services:

   ```bash
   sudo systemctl restart aquacore-relays.service aquacore.service
   ```

7. Calibrate Bottle B using its web calibration modal, with the outlet in a cup.
   Set an independent dose, time, and weekday selection. Neither configuring
   the schedule nor clicking Save immediately actuates the pump.

## API / compatibility

Existing `/api/fertilizer/*` routes remain Pump 1 and are unchanged. The
second pump uses `/api/fertilizer/2/*` for status, manual start/stop, calibration
and weekday schedules. The Pump 2 activation time and milliliter dose use the
existing autosave field endpoint with `fertilizer2_time` and
`fertilizer2_dose_ml`.

Both pumps are independent; no change to pH/TDS sensing or the system
metrics interval is required.
