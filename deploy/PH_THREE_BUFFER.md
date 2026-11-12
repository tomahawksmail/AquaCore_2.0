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
   temperature, and temperature-adjusted buffer reference. Check the boxes
   and click **Save three-point pH calibration** after all three readings.
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
connection. If A1 is not installed, leave NTC_ENABLED=0; the temperature
tab cannot calibrate an absent thermistor. pH calibration temperature is
still entered manually from the glass thermometer.

No web/Orange Pi hardware verification is implied by source-only tests.
