-- Run once on an existing AquaCore MariaDB installation before deploying code.
-- MariaDB supports ADD COLUMN IF NOT EXISTS.
ALTER TABLE sensor_calibration
  ADD COLUMN IF NOT EXISTS tds_factor DOUBLE NOT NULL DEFAULT 0.2626,
  ADD COLUMN IF NOT EXISTS ph_factor DOUBLE NOT NULL DEFAULT 1.0,
  ADD COLUMN IF NOT EXISTS temp_factor DOUBLE NOT NULL DEFAULT 1.0;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
