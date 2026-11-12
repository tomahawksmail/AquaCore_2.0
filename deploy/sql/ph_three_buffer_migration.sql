-- Fresh three-buffer calibration fields, do not disturb legacy pH 7/4.
-- Apply BEFORE restarting the web UI and TDS collector.
-- MariaDB 10.6+ syntax; safe to rerun on an existing sensor_calibration table.
ALTER TABLE sensor_calibration
  ADD COLUMN IF NOT EXISTS ph401_voltage DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph686_voltage DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph918_voltage DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph401_reference DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph686_reference DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph918_reference DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph401_temp_c DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph686_temp_c DOUBLE NULL,
  ADD COLUMN IF NOT EXISTS ph918_temp_c DOUBLE NULL;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
