-- Run once before deploying sensor calibration UI or the new collector.
CREATE TABLE IF NOT EXISTS sensor_calibration (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  temp_offset_c DOUBLE NOT NULL DEFAULT 0,
  ntc_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ntc_supply_v DOUBLE NOT NULL DEFAULT 3.3,
  tds_factor DOUBLE NOT NULL DEFAULT 0.2626,
  ph_factor DOUBLE NOT NULL DEFAULT 1.0,
  temp_factor DOUBLE NOT NULL DEFAULT 1.0,
  ph7_voltage DOUBLE NULL,
  ph4_voltage DOUBLE NULL,
  ph401_voltage DOUBLE NULL,
  ph686_voltage DOUBLE NULL,
  ph918_voltage DOUBLE NULL,
  ph401_reference DOUBLE NULL,
  ph686_reference DOUBLE NULL,
  ph918_reference DOUBLE NULL,
  ph401_temp_c DOUBLE NULL,
  ph686_temp_c DOUBLE NULL,
  ph918_temp_c DOUBLE NULL,
  temp_updated_at DATETIME NULL,
  ph_updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
