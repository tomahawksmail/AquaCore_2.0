-- Fresh installation of A1-calibrated two-buffer pH (6.86=2.54V, 4.01=3.04V at 25C).
-- Use ph_two_buffer_ntc_migration.sql for existing installations.
CREATE TABLE IF NOT EXISTS sensor_calibration (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  ntc_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ntc_supply_v DOUBLE NOT NULL DEFAULT 3.3,
  temp_factor DOUBLE NOT NULL DEFAULT 1.0,
  temp_offset_c DOUBLE NOT NULL DEFAULT 0,
  temp_updated_at DATETIME NULL,
  tds_factor DOUBLE NOT NULL DEFAULT 0.2626,
  ph686_voltage DOUBLE NOT NULL DEFAULT 2.54,
  ph401_voltage DOUBLE NOT NULL DEFAULT 3.04,
  ph686_temp_c DOUBLE NOT NULL DEFAULT 25.0,
  ph401_temp_c DOUBLE NOT NULL DEFAULT 25.0,
  ph_updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);
