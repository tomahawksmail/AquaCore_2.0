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

### Temperature compensation

The supplied packet labels are valid at 25°C, but the actual buffer pH
varies with solution temperature. The code linearly interpolates a standard
reference table for 0–50°C; e.g. **22.5°C → pH 4.005, 6.870, 9.200**.
This is a **typical reference**, not a guarantee for every buffer powder.
If a powder manufacturer supplies a different temperature chart, their
chart is authoritative and may require updating the table. The new
calibration applies these reference values during capture. It does not
implement full Nernst-based electrode compensation between calibration
temperature and later aquarium measurement temperature.

### ADS1115 concurrency

The Web 500ms live preview and the background collector use the same
ADS1115 I²C mux. All calls through `sensorstest.adc_read` use an exclusive
`/run/lock/aquacore-ads1115-2-48.lock` file lock per ADC transaction, so
their mux writes/reads cannot overlap across processes. This requires the
normal writable `/run/lock` directory on Armbian. The web process needs
membership in the `i2c` group.

### Troubleshooting

```bash
sudo journalctl -u aquacore.service -n 80 --no-pager
sudo journalctl -u aquacore-tds.service -n 80 --no-pager
sudo mariadb _AquaCore_ -e "SELECT ph401_voltage,ph686_voltage,ph918_voltage,ph401_temp_c,ph686_temp_c,ph918_temp_c FROM sensor_calibration WHERE id=1;"
```

If the displayed A0 voltage does not stabilize, check electrode wetting,
distilled-water rinse, grounding/noise, ADC supply voltage, and probe
connection. If A1 is not installed, leave `ntc_enabled=0` in MariaDB; the temperature
tab cannot calibrate an absent thermistor. pH calibration temperature is
still entered manually from the glass thermometer.

No web/Orange Pi hardware verification is implied by source-only tests.

### How live pH, dashboard values and charts are sampled

**The AquaCore collector now captures five A0 pH voltages spread over
about four seconds**, approximately one second between measurements,
rather than taking all five nearly at once. It calculates the
**median voltage**, converts that once with the saved pH calibration
curve, then inserts the resulting single pH value in the MariaDB
`data.ph` column. It does not write each raw sub-sample into the history.

- By default, `aquacore-tds.service` runs the collector using
  `--samples 5 --interval 30`. The interval waits **after** a completed
  acquisition, so the typical time between saved rows may be slightly
  longer than 30 seconds. The `--samples` option supports 1–30; use
  **5** for spike-resistant filtering.
- The dashboard's **current pH** card reads the latest saved row in
  `data`. The **history chart** reads the same table but uses SQL
  `AVG(ph)` to aggregate values into time buckets. Both therefore use
  the collector's median-filtered measurements; the chart is not a
  separate direct sensor input.
- The pH calibration dialog requests A0 at roughly **0.5-second
  intervals**. It displays **raw A0 voltage** without smoothing, so the
  operator can judge stability. Only the *calculated current pH
  estimate* is smoothed using a rolling median of the last **up to
  five** successful pH estimates. This does not change the calibration
  voltage captured by a buffer button.
- Temperature and TDS already use the median of up to five quick ADC
  samples in the collector. They have not been changed by the pH
  filtering update. Buffer *calibration captures* retain their separate
  12-sample stable-reading validation.

**What median filtering can/cannot fix:** One isolated erroneous
read among five will not dominate the median. A sustained shift
(e.g. pH 4.01 → 4.50 over several seconds) can still pass through the
filter, because it may reflect probe equilibration, wiring/grounding
noise, incorrect buffer preparation, or a genuine changing solution.
Do not silently clamp such changes or treat a displayed median as
proof of correct calibration. Let the pH electrode settle in each
reference buffer before capturing; verify power supply noise and
the saved 4.01/6.86/9.18 calibration curve.

Check the collector's actual saved pH and logging:

```bash
sudo journalctl -u aquacore-tds.service -n 40 --no-pager
sudo mariadb _AquaCore_ -e \
  "SELECT Datetime, temp, ph, tds FROM data ORDER BY Id DESC LIMIT 10;"
```

## A1 temperature-aware pH calibration and measurement

When the optional **10 kΩ NTC B3950** probe is installed on ADS1115 **A1**,
AquaCore can use it for two separate purposes:

1. **During buffer capture:** the pH dialog has a checkbox **Use A1 NTC
   temperature instead (both probes in the SAME buffer)**. This is
   deliberately **off by default**. To enable it, wire and configure A1,
   then calibrate A1 against a trusted thermometer on the Temperature tab.
   For every pH 6.86 / 4.01 / 9.18 capture, immerse **both** the pH probe
   and the temperature probe in that specific reference glass. When the
   checkbox is selected, the server reads a fresh A1 sample during the
   capture, applies the saved A1 calibration, uses the matching
   **temperature-adjusted standard-buffer pH**, and saves both reference
   voltage and buffer temperature. No temperature is guessed from the
   aquarium. Manual temperature entry remains available if the NTC stays
   permanently in the aquarium while pH buffers are tested elsewhere.
2. **During regular monitoring:** when calibrated A1 is measuring the
   **same aquarium water** as the pH electrode, and a completed three-point
   pH calibration with recorded temperatures is present, the collector and
   calibration preview adjust the **pH electrode slope** using the Nernst
   absolute-temperature relationship. AquaCore uses the measured slope of
   each 4.01↔6.86 or 6.86↔9.18 calibration interval and scales it by
   `(T_calibration + 273.15) / (T_water + 273.15)`. The pH 6.86
   calibration point is the near-neutral anchor. Temperature-compensated
   pH is saved in `data.ph`, used for the current dashboard, and averaged
   into the historical chart. Existing saved records are not modified.

This is **electrode slope compensation**, not a conversion of aquarium
water chemistry to a hypothetical pH at 25°C. The actual pH of any water
can change with temperature. The Nernst calculation is a first-order
approximation; it assumes the amplifier's gain and electrode reference
offset remain stable. For best calibration, allow the three reference
buffers to reach similar temperatures, use the *manufacturer's* buffer
temperature chart when available, and verify the result in a fresh
reference solution. See [HORIBA's guide to pH ATC](https://www.horiba.com/pol/water-quality/support/technical-tips/bench-meters/automatic-temperature-compensation-in-ph-measurement/).

If A1 is unplugged, disabled, unreadable, or has **not** been calibrated
(`temp_updated_at` is empty), AquaCore keeps the existing
non-temperature-compensated pH calculation and reports **ATC OFF**; it
must not substitute the collector's nominal `--temperature 22` fallback
as if it were a measured pH temperature.

### Wiring, MariaDB settings and startup

**Current planned installation: all sensor/ADS1115 boards are powered at
5 V. The NTC and its fixed resistor are NOT YET INSTALLED. Leave A1 disabled
until the parts arrive.** Connect the passive divider only after powering down:

```text
                +5.0 V
                   |
            10 kΩ fixed resistor
                   |
ADS1115 A1 --------+---- NTC 10 kΩ B3950 ---- GND

ADS1115 A0 <------ PH-4502C analog PO
                   (pH electrode attached via BNC)
ADS1115 VDD <----- 5.0 V
ADS1115 GND <----- common GND
```

With a matched 10 kΩ NTC at 25°C, the nominal A1 voltage is **2.50 V**.
The NTC divider voltage is stored in
`sensor_calibration.ntc_supply_v` (**5.0 V** by default), and
`sensor_calibration.ntc_enabled` defaults to **0 / disabled**.
**Do not set `NTC_ENABLED` or `NTC_SUPPLY_V` in
`/etc/aquacore/web.env`: these are no longer used.**

Your Orange Pi GPIO is 3.3 V logic **even though the ADS1115 breakout is
supplied at 5 V**. A breakout with 5 V I²C pull-ups must not connect directly
to Orange Pi 3.3 V SDA/SCL; verify the actual breakout or install a suitable
bidirectional level shifter. The ADC's PGA is still ±4.096 V, so inputs above
that level saturate even when VDD is 5 V. Keep common ground and verify
real voltages before attaching hardware.

**Required database migration (before deploying the web/collector code):**

```bash
sudo systemctl stop aquacore.service aquacore-tds.service
sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/ntc_settings_migration.sql
sudo systemctl start aquacore.service aquacore-tds.service
sudo mariadb _AquaCore_ -e \
  "SELECT ntc_enabled,ntc_supply_v FROM sensor_calibration WHERE id=1;"
```

**After installing** the thermistor and fixed resistor, open
**Settings → Sensor Calibration → Temperature**. Check
**Enable A1 NTC**, verify **5.00 V**, click **Save A1 hardware settings**.
The collector reads those values from MariaDB on every sample, so no
environment edit is needed. Enabling A1 or changing its divider voltage
requires recalibrating temperature (the old temperature calibration is
invalidated). If no probe is installed, leave the checkbox unchecked.

Then **calibrate A1 first**: Settings → Sensor calibration → Temperature;
immerse A1 and a trusted glass thermometer in the same water, Capture A1,
enter measured °C, Save temperature. For fresh pH reference liquids, move
the two sensors into the *same* buffer before selecting the A1 checkbox
and pressing Capture; otherwise leave the checkbox off and enter the
glass thermometer temperature manually. The pH preview shows ATC ON/OFF
and the currently measured temperature when available.

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
