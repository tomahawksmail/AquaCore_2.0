-- Move A1 NTC hardware configuration from environment variables to MariaDB.
-- Install BEFORE deploying updated web/collector code.
-- User has not installed the thermistor yet: keep NTC disabled by default.
-- Existing sensor_calibration data and pH references are not modified.
ALTER TABLE sensor_calibration
  ADD COLUMN IF NOT EXISTS ntc_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ntc_supply_v DOUBLE NOT NULL DEFAULT 5.0;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
