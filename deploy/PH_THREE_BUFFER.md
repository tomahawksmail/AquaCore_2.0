# AquaCore 2.0 — three-tab sensor calibration

**Deployment:** New calibration UI for TDS (A3), NTC temperature (A1), and pH
(A0) with three actual reference buffers: **4.01, 6.86, and 9.18 at 25°C**.
The web dialog polls live A0/A1/A3 voltages about **every 500 milliseconds**,
skipping overlapping browser requests. The capture buttons measure a *stable*
median over about 1 second; they do not blindly freeze a single volatile
preview frame. Access is restricted to signed-in administrators.

## Upgrade an existing Orange Pi (without deleting measurements)

Back up the database first. The migration adds columns and does not overwrite
existing calibration. The browser and TDS worker require the new columns.

```bash
sudo mariadb-dump _AquaCore_ > ~/aquacore-before-3point-ph.sql
sudo -u aquacore git -C /opt/aquacore pull --ff-only origin master

# Stop the web reader and collector while changing schema; keep relay service
# running so existing cooler/GPIO control is unaffected.
sudo systemctl stop aquacore.service aquacore-tds.service
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/ph_three_buffer_migration.sql
sudo systemctl start aquacore.service aquacore-tds.service

sudo systemctl is-active aquacore.service aquacore-tds.service
```

**Do not** apply the migration before merging/deploying the matching code
without the two services stopped. If the web/collector starts before the
migration, its queries for the new fields fail. No relay service restart is
required. New installations using `deploy/sql/sensor_calibration.sql`
already get all the columns.

## Temperature sensor hardware wiring — ADS1115 A1

**Sensor:** waterproof two-wire **NTC 10 kΩ at 25°C, B3950** thermistor.
**Additional component:** a separate **10 kΩ fixed resistor** (1% tolerance
preferred). AquaCore implements a **3.3 V voltage divider**, not a direct
analog connection to the Orange Pi GPIO.

### Electrical schematic (actual AquaCore conversion polarity)

```text
      Orange Pi Zero 2W / ADS1115                  Waterproof probe

                 +3.3 V
                    |
                    +---------------------------> ADS1115 VDD
                    |
                [10 kΩ fixed resistor]
                    |
                    +---------------------------> ADS1115 A1
                    |
                [NTC thermistor]
                [10 kΩ / B3950]
                    |
     GND ------------+---------------------------> ADS1115 GND

     Orange Pi I²C SDA --------------------------> ADS1115 SDA
     Orange Pi I²C SCL --------------------------> ADS1115 SCL
     Orange Pi GND ------------------------------> ADS1115 GND

     ADS1115 ADDR -> GND for address 0x48 (if the breakout
                      uses a configurable ADDR pin)
```

**Important details:**

- Connect the **fixed 10 kΩ resistor between +3.3 V and the junction
  attached to A1**; connect the **NTC between A1 and GND**. Reversing their
  order makes the default temperature conversion incorrect.
- The two wires of a bare NTC have **no polarity**.
- The Orange Pi and ADS1115 must **share a common ground**. Use **3.3 V** for
  both the ADC supply and the divider; do **not** feed 5 V into the ADC input
  or Orange Pi 3.3 V GPIO/I²C pins.
- The existing AquaCore sensor map is **A0 = pH module analog output**,
  **A1 = NTC voltage divider**, and **A3 = TDS analog output**.
  Do not leave an old pH-module **T1/T2** signal connected to A1 at the
  same time as the NTC.
- Use the correct **SDA and SCL header pins for the Orange Pi Zero 2W's
  active `/dev/i2c-2` bus**. Physical header pin numbering is intentionally
  omitted here because it should be checked against the board's specific
  header/pinmux configuration.
- Disconnect power before changing wiring; inspect for shorts and exposed
  metal near the aquarium.

### Sanity check before enabling NTC

At **25°C**, the NTC is approximately 10 kΩ and the A1 voltage should be
around **1.65 V** on a 3.3 V supply with a 10 kΩ fixed resistor.
With **warmer water**, NTC resistance and A1 voltage **decrease**; colder
water increases both. Readings vary with part tolerance.

The actual software equation in `sensor_conversion.py` is

```text
R_NTC = 10,000 Ω × V_A1 / (3.3 V − V_A1)
```

followed by the B3950 thermistor beta equation. This formula assumes the
specific resistor ordering drawn above.

Check the hardware as the service user **after wiring**:

```bash
sudo -u aquacore -g i2c \
  /opt/aquacore/.venv/bin/python /opt/aquacore/sensorstest.py \
  --bus 2 --all-channels --ntc --once
```

Look for `A1=... V` and `water_temp=... C` (the thermistor temperature).
A floating/disconnected A1 may still show an arbitrary voltage; **a raw A1
voltage is not proof the NTC is correctly installed**. In the earlier AquaCore
web API response, `ntc_enabled=false`, so water temperature was deliberately
not being calculated. Only enable the feature after installing the divider.

### Enable NTC and calibrate it

Edit the Orange Pi service environment file:

```bash
sudoedit /etc/aquacore/web.env
```

Set or update these values (do not add duplicate variable names):

```ini
NTC_ENABLED=1
NTC_SUPPLY_V=3.3
```

Then restart **only** the web UI and TDS collector, not the relay/cooler
controller:

```bash
sudo systemctl restart aquacore.service aquacore-tds.service
```

In **Settings → Sensor calibration → Temperature**:

1. Immerse the NTC probe and a separate **glass aquarium thermometer** in the
   same water; allow them to reach the same stable temperature.
2. Check live **A1 voltage** and the uncalibrated temperature estimate.
3. Click **Capture A1** to record a stable reference. The API collects a median
   of 12 voltage samples and rejects highly unstable readings.
4. Type the actual glass thermometer reading (°C) in the reference input
   (permitted range **5–40°C**).
5. Click **Save temperature**. The server stores an offset so the calculated
   temperature matches your reference at that measurement point. It rejects
   an offset larger than **5°C** and requires the reference capture to be
   younger than **15 minutes**.
6. Return the probe to the aquarium. New collector samples will use
   `raw_NTC_C × temp_factor + temp_offset_c`. Old history is not rewritten.

If there is no NTC or the divider is incorrect, leave `NTC_ENABLED=0`.
Manually entering **buffer-liquid temperature** in the pH tab is independent
of having an NTC sensor installed.

## Use the dialog

1. Open Settings > Sensor calibration.
2. **TDS tab**: view A3 volts and estimated ppm. Enter the TDS multiplier
   only if measured with a trusted standard, then click Save TDS multiplier.
   Existing TDS calibration is not altered by pH or temperature saves.
3. **Temperature tab**: place the A1 NTC and a glass aquarium thermometer in
   the same water, click Capture stable A1, enter thermometer °C, click Save.
   A1 needs a 10k/B3950 thermistor and the correct 10k pull-up divider.
4. **pH tab**: prepare separate **distilled-water** pH 4.01, 6.86, 9.18
   buffer solutions using the packet's exact water volume; do not use tap or
   mineralized drinking water. Prefer to begin at 6.86, then rinse gently
   between the other buffers. Let the electrode equilibrate and read the
   **liquid** temperature on the glass thermometer. Enter that temperature
   into the *one shared* input, then click its matching Capture button.
   Change the field if the next glass is at a different temperature.
5. All three saved voltage labels show their capture voltage, thermometer
   temperature, and temperature-adjusted buffer reference. The Save
   button enables automatically once all three captures are complete—there
   is no extra confirmation checkbox. Click **Save pH calibration**.
   If the voltages are crossed, almost identical, saturated, or stale
   (>15 min), the server rejects them and retains the older calibration.
6. After saving, new pH samples use the **piecewise linear three-point curve**
   (4.01→6.86 and 6.86→9.18), and the previous pH slope multiplier is reset
   to 1.0 to avoid double calibration. Old sample history stays unchanged.

## pH calibration checklist (4.01 / 6.86 / 9.18)

This is a **three-buffer calibration**, not the older two-buffer pH 7.00/4.00
workflow. All values refer to the actual **buffer solutions**, not tap water
or aquarium water.

1. Prepare each powdered buffer in a clean, separately labeled glass with
   **distilled/deionized water**, using the exact volume stated on its
   packet. Allow the solution to reach room temperature.
2. If the electrode has been stored dry, hydrate it as its manufacturer
   instructs (usually in the correct electrode storage solution, not
   distilled water). Rinse with distilled water between different buffers,
   gently **blot**, and avoid rubbing the sensitive bulb.
3. Start with **6.86**. Place the pH electrode fully enough into the buffer
   to cover the sensing bulb and junction. Wait for **A0 live voltage** to
   settle. Read the buffer's actual temperature with a **glass thermometer**,
   enter it in the **one shared pH liquid-temperature input**, and press
   **Capture 6.86**.
4. Rinse gently, move to **4.01**, adjust the shared temperature field if
   necessary, and press **Capture 4.01** after stabilization.
5. Rinse gently, move to **9.18**, adjust the temperature field if necessary,
   and press **Capture 9.18** after stabilization.
6. Confirm that all **three capture cards** show their captured voltage and
   temperature; the progress indicator reads **3/3**. Click
   **Save pH calibration**. **There is no extra confirmation checkbox.**
   The server checks the stored captures, rejects stale captures (over 15 min),
   saturated and non-monotonic voltages, and keeps the previous saved pH curve
   if validation fails.
7. After saving, verify the probe in a **fresh buffer**. The new collector
   uses the saved three-point piecewise-linear curve for subsequent aquarium
   readings. Do not use an unverified pH result to automatically regulate CO₂.

At **22.5°C**, the current AquaCore reference table gives approximately:

| Buffer packet nominal value (at 25°C) | Reference used at 22.5°C |
| --- | ---: |
| 4.01 | 4.005 |
| 6.86 | 6.870 |
| 9.18 | 9.200 |

These values are from AquaCore's built-in table. **The buffer powder's
manufacturer-specific temperature chart takes precedence** if it differs.
This adjusts calibration buffer values only; it is not a full Nernst-based
live compensation for changing aquarium temperatures.

**Note:** Voltage captured from a probe in aquarium water is **not** a
certified pH reference. Do not treat a raw A0 reading, such as 1.08906 V,
as if it directly indicates a particular pH.

### Buffer temperature compensation

The supplied packet labels are valid at 25°C, but the actual buffer pH
varies with solution temperature. The code linearly interpolates a standard
reference table for 0–50°C; e.g. **22.5°C → pH 4.005, 6.870, 9.200**.
This is a **typical reference**, not a guarantee for every buffer powder.
If a powder manufacturer supplies a different temperature chart, their
chart is authoritative and may require updating the table. The new
calibration applies these reference values during capture. It does not
implement full Nernst-based electrode compensation between calibration
temperature and later aquarium measurement temperature.

## TDS calibration checklist (A3)

1. Read the **live A3 voltage** in the TDS tab. The displayed ppm estimate
   uses a provisional coefficient until compared against a **known TDS or
   conductivity standard**.
2. Follow the standard's specified temperature and ppm/EC convention.
   If using a TDS standard, ensure its ppm conversion scale matches the
   one you intend to use.
3. Adjust the **TDS multiplier**, compare the estimated value with the
   reference, then explicitly click **Save TDS factor**.
4. The collector applies the saved TDS multiplier to new readings; it does not
   recalculate older measurements.

**Do not calibrate TDS from distilled water alone**, because near-zero TDS
does not establish a useful scaling factor. Raw ADS1115 voltage by itself
does not establish a certified TDS value.

## ADS1115 concurrency

The Web 500ms live preview and the background collector use the same
ADS1115 I²C mux. All calls through `sensorstest.adc_read` use an exclusive
`/run/lock/aquacore-ads1115-2-48.lock` file lock per ADC transaction, so
their mux writes/reads cannot overlap across processes. This requires the
normal writable `/run/lock` directory on Armbian. The web process needs
membership in the `i2c` group.

## Troubleshooting

```bash
sudo journalctl -u aquacore.service -n 80 --no-pager
sudo journalctl -u aquacore-tds.service -n 80 --no-pager
sudo mariadb _AquaCore_ -e "SELECT ph401_voltage,ph686_voltage,ph918_voltage,ph401_temp_c,ph686_temp_c,ph918_temp_c FROM sensor_calibration WHERE id=1;"
```

If the displayed A0 voltage does not stabilize, check electrode wetting,
distilled-water rinse, grounding/noise, ADC supply voltage, and probe
connection. If A1 is not installed, leave NTC_ENABLED=0; the temperature
tab cannot calibrate an absent thermistor. pH calibration temperature is
still entered manually from the glass thermometer.

No web/Orange Pi hardware verification is implied by source-only tests.

## Live voltage troubleshooting

Live A0, A1, and A3 readings are independent. A disconnected/saturated
A1 thermistor or A3 TDS input must **not** hide a healthy pH A0 voltage.
An unavailable channel displays `— V`, with the channel-specific error
in the modal's footer. The 500ms UI poll skips overlapping requests.
If the calibration database cannot be read, raw live voltages are still
returned, with a warning that the saved calibration configuration is unavailable.
To troubleshoot permission/I²C errors:

```bash
sudo journalctl -u aquacore.service -n 80 --no-pager
sudo -u aquacore /opt/aquacore/.venv/bin/python /opt/aquacore/sensorstest.py \
  --bus 2 --all-channels --once
```

Do not claim a voltage is current when the channel read fails. When a pH
reading is unavailable, verify the A0 wiring and the ADS1115 on I²C bus 2,
address 0x48. Never connect probe-module outputs above the ADC supply.
