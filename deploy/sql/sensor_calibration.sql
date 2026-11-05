-- Run once before deploying sensor calibration UI or the new collector.
CREATE TABLE IF NOT EXISTS sensor_calibration (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  temp_offset_c DOUBLE NOT NULL DEFAULT 0,
  ph7_voltage DOUBLE NULL,
  ph4_voltage DOUBLE NULL,
  temp_updated_at DATETIME NULL,
  ph_updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
