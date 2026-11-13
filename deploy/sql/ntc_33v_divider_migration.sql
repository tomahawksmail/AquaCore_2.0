-- Switch ONLY the optional A1 thermistor divider from 5.0V to 3.3V.
-- ADS1115 VDD and PH-4502C VCC remain at 5V.
-- Apply after the earlier ntc_settings_migration.sql when upgrading.
-- Do not silently change an enabled/provisioned NTC circuit.
ALTER TABLE sensor_calibration
  MODIFY COLUMN ntc_supply_v DOUBLE NOT NULL DEFAULT 3.3;

-- This user's A1 thermistor is not installed yet. Convert old disabled
-- defaults (5.0V) to 3.3V while leaving enabled/custom setups unchanged.
UPDATE sensor_calibration
   SET ntc_supply_v = 3.3
 WHERE ntc_enabled = 0 AND ABS(ntc_supply_v - 5.0) < 0.0001;
