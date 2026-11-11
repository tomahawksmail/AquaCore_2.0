-- AquaCore 2.0 - EMPTY DATABASE BOOTSTRAP (MariaDB 11.x)
-- Generated from the repository's existing base table definitions plus current migrations.
-- Apply ONLY to a NEW, empty instance. This file is schema-only except for required
-- singleton configuration rows. No users, Telegram IDs, WiFi credentials, sensor
-- readings, system metrics, overrides or log history are included.
-- IMPORTANT: Keep relays/CO2/UV/pumps disconnected until installation and calibration.
CREATE DATABASE IF NOT EXISTS `_AquaCore_` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `_AquaCore_`;

-- Original base table definitions; counters widened to BIGINT for long-running hosts.
CREATE TABLE IF NOT EXISTS `data` (
  `Id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `Datetime` datetime DEFAULT NULL,
  `temp` float unsigned DEFAULT NULL,
  `ph` float unsigned DEFAULT NULL,
  `tds` float unsigned DEFAULT NULL,
  PRIMARY KEY (`Id`) USING BTREE,
  KEY `Datetime` (`Datetime`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `loging` (
  `Id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `User` varchar(50) DEFAULT NULL,
  `Event` varchar(255) DEFAULT NULL,
  `Datetime` datetime DEFAULT NULL,
  PRIMARY KEY (`Id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `manual_overrides` (
  `device` varchar(48) NOT NULL,
  `desired` varchar(10) NOT NULL,
  `created_at` datetime NOT NULL,
  `until_at` datetime NOT NULL,
  PRIMARY KEY (`device`),
  KEY `idx_manual_until` (`until_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `options` (
  `history` int(11) DEFAULT NULL,
  `min_temp` float unsigned DEFAULT NULL,
  `max_temp` float unsigned DEFAULT NULL,
  `min_ph` float unsigned DEFAULT NULL,
  `max_ph` float unsigned DEFAULT NULL,
  `min_tds` float unsigned DEFAULT 0,
  `max_tds` float unsigned DEFAULT NULL,
  `co2_on` time DEFAULT NULL,
  `co2_off` time DEFAULT NULL,
  `o2_on` time DEFAULT NULL,
  `o2_off` time DEFAULT NULL,
  `UV_on` time DEFAULT NULL,
  `UV_off` time DEFAULT NULL,
  `Master_light_on` time DEFAULT NULL,
  `Master_light_off` time DEFAULT NULL,
  `Backlight_on` time DEFAULT NULL,
  `Backlight_off` time DEFAULT NULL,
  `PlantL_on` time DEFAULT NULL,
  `PlantL_off` time DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `psutil` (
  `Id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `Datetime` datetime DEFAULT NULL,
  `scpufreq_cur` int(11) unsigned DEFAULT NULL,
  `scpufreq_min` int(11) unsigned DEFAULT NULL,
  `scpufreq_max` int(11) unsigned DEFAULT NULL,
  `cpus_percent_0` int(11) unsigned DEFAULT NULL,
  `cpus_percent_1` int(11) unsigned DEFAULT NULL,
  `cpus_percent_2` int(11) unsigned DEFAULT NULL,
  `cpus_percent_3` int(11) unsigned DEFAULT NULL,
  `RAM_total` int(11) unsigned DEFAULT NULL,
  `RAM_available` int(11) unsigned DEFAULT NULL,
  `RAM_percent` int(11) unsigned DEFAULT NULL,
  `RAM_used` int(11) unsigned DEFAULT NULL,
  `RAM_free` int(11) unsigned DEFAULT NULL,
  `RAM_active` int(11) unsigned DEFAULT NULL,
  `RAM_inactive` int(11) unsigned DEFAULT NULL,
  `RAM_buffers` int(11) unsigned DEFAULT NULL,
  `RAM_cached` int(11) unsigned DEFAULT NULL,
  `RAM_shared` int(11) unsigned DEFAULT NULL,
  `RAM_slab` int(11) unsigned DEFAULT NULL,
  `cpu_thermal_cur` int(11) unsigned DEFAULT NULL,
  `cpu_thermal_high` int(11) unsigned DEFAULT NULL,
  `cpu_thermal_crit` int(11) unsigned DEFAULT NULL,
  `gpu_thermal_cur` int(11) unsigned DEFAULT NULL,
  `gpu_thermal_high` int(11) unsigned DEFAULT NULL,
  `gpu_thermal_crit` int(11) unsigned DEFAULT NULL,
  `ve_thermal_cur` int(11) unsigned DEFAULT NULL,
  `ddr_thermal_cur` int(11) unsigned DEFAULT NULL,
  `net_bytes_sent` BIGINT UNSIGNED DEFAULT NULL,
  `net_bytes_recv` BIGINT UNSIGNED DEFAULT NULL,
  `net_packets_sent` BIGINT UNSIGNED DEFAULT NULL,
  `net_packets_recv` BIGINT UNSIGNED DEFAULT NULL,
  `net_errin` BIGINT UNSIGNED DEFAULT NULL,
  `net_errout` BIGINT UNSIGNED DEFAULT NULL,
  `net_dropin` BIGINT UNSIGNED DEFAULT NULL,
  `net_dropout` BIGINT UNSIGNED DEFAULT NULL,
  `disk_read_count` BIGINT UNSIGNED DEFAULT NULL,
  `disk_write_count` BIGINT UNSIGNED DEFAULT NULL,
  `disk_read_bytes` BIGINT UNSIGNED DEFAULT NULL,
  `disk_write_bytes` BIGINT UNSIGNED DEFAULT NULL,
  `disk_read_time` BIGINT UNSIGNED DEFAULT NULL,
  `disk_write_time` BIGINT UNSIGNED DEFAULT NULL,
  `disk_busy_time` BIGINT UNSIGNED DEFAULT NULL,
  `disk_usage_total` BIGINT UNSIGNED DEFAULT NULL,
  `disk_usage_used` BIGINT UNSIGNED DEFAULT NULL,
  `disk_usage_free` BIGINT UNSIGNED DEFAULT NULL,
  `disk_usage_percent` int(11) unsigned DEFAULT NULL,
  PRIMARY KEY (`Id`) USING BTREE,
  KEY `Datetime` (`Datetime`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `status` (
  `co2_status` char(10) DEFAULT NULL,
  `o2_status` char(10) DEFAULT NULL,
  `UV_status` char(10) DEFAULT NULL,
  `heater_status` char(10) DEFAULT NULL,
  `MasterL_status` char(10) DEFAULT NULL,
  `PlantL_status` char(10) DEFAULT NULL,
  `Backlight_status` char(10) DEFAULT 'unchecked'
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `telegram_users` (
  `telegram_id` bigint(20) unsigned NOT NULL,
  `role` varchar(16) NOT NULL DEFAULT 'viewer',
  `added_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`telegram_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `users` (
  `U_Id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `Username` varchar(50) DEFAULT NULL,
  `UserPassword` varchar(255) DEFAULT NULL,
  `email` varchar(50) DEFAULT NULL,
  `Role` int(1) unsigned zerofill NOT NULL,
  PRIMARY KEY (`U_Id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE IF NOT EXISTS `WiFi` (
  `SSID` varchar(50) DEFAULT NULL,
  `PASSWORD` varchar(50) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;


-- Applied migration: deploy/sql/fertilizer_options.sql
-- Run with aquacore.service and aquacore-relays.service STOPPED.
-- Requires the existing options singleton and status table.
-- Safe to rerun. New installations default to OFF and uncalibrated.
-- Does not read or drop the old fertilizer_pump table.
ALTER TABLE `options`
  ADD COLUMN IF NOT EXISTS `fertilizer_start_time` TIME NOT NULL DEFAULT '12:00:00',
  ADD COLUMN IF NOT EXISTS `fertilizer_weekdays` TINYINT UNSIGNED NOT NULL DEFAULT 127,
  ADD COLUMN IF NOT EXISTS `fertilizer_dose_ml` DECIMAL(7,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_ml_per_second` DECIMAL(10,5) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `fertilizer_last_run_date` DATE DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `fertilizer_manual_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_manual_processed_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_manual_requested_at` DATETIME DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `fertilizer_manual_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_manual_kind` VARCHAR(16) NOT NULL DEFAULT 'dose',
  ADD COLUMN IF NOT EXISTS `fertilizer_calibration_saved_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_kind` VARCHAR(16) NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_state` VARCHAR(16) NOT NULL DEFAULT 'idle',
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_started_at` DATETIME(3) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_finished_at` DATETIME(3) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `fertilizer_pulse_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0;

-- This already exists in your installation; IF NOT EXISTS keeps it idempotent.
ALTER TABLE `status`
  ADD COLUMN IF NOT EXISTS `fertilizer_pump_status`
  VARCHAR(10) NOT NULL DEFAULT 'unchecked';


-- Applied migration: deploy/sql/fertilizer_pump2_migration.sql
-- Separate Bottle B dosing state. Pump 1 stays untouched in options.
-- Run this before restarting the web or relay services with the new code.
CREATE TABLE IF NOT EXISTS `fertilizer_pump2` (
  `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  `fertilizer_start_time` TIME NOT NULL DEFAULT '12:30:00',
  `fertilizer_weekdays` TINYINT UNSIGNED NOT NULL DEFAULT 127,
  `fertilizer_dose_ml` DECIMAL(7,2) NOT NULL DEFAULT 0,
  `fertilizer_ml_per_second` DECIMAL(10,5) DEFAULT NULL,
  `fertilizer_last_run_date` DATE DEFAULT NULL,
  `fertilizer_manual_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `fertilizer_manual_processed_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `fertilizer_manual_requested_at` DATETIME DEFAULT NULL,
  `fertilizer_manual_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0,
  `fertilizer_manual_kind` VARCHAR(16) NOT NULL DEFAULT 'dose',
  `fertilizer_calibration_saved_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `fertilizer_pulse_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `fertilizer_pulse_kind` VARCHAR(16) NOT NULL DEFAULT '',
  `fertilizer_pulse_state` VARCHAR(16) NOT NULL DEFAULT 'idle',
  `fertilizer_pulse_started_at` DATETIME(3) DEFAULT NULL,
  `fertilizer_pulse_finished_at` DATETIME(3) DEFAULT NULL,
  `fertilizer_pulse_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO `fertilizer_pump2` (`id`) VALUES (1);
ALTER TABLE `status` ADD COLUMN IF NOT EXISTS `fertilizer_pump2_status`
 VARCHAR(10) NOT NULL DEFAULT 'unchecked';


-- Applied migration: deploy/sql/sensor_calibration.sql
-- Run once before deploying sensor calibration UI or the new collector.
CREATE TABLE IF NOT EXISTS sensor_calibration (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  temp_offset_c DOUBLE NOT NULL DEFAULT 0,
  tds_factor DOUBLE NOT NULL DEFAULT 0.2626,
  ph_factor DOUBLE NOT NULL DEFAULT 1.0,
  temp_factor DOUBLE NOT NULL DEFAULT 1.0,
  ph7_voltage DOUBLE NULL,
  ph4_voltage DOUBLE NULL,
  temp_updated_at DATETIME NULL,
  ph_updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO sensor_calibration (id) VALUES (1);


-- Applied migration: deploy/sql/cooler_thresholds.sql
-- AquaCore CPU fan thresholds (default behavior unchanged).
-- Run once before deploying the web and relay-worker changes.
ALTER TABLE `options`
  ADD COLUMN IF NOT EXISTS `cooler_on_c` DECIMAL(4,1) NOT NULL DEFAULT 70.0,
  ADD COLUMN IF NOT EXISTS `cooler_off_c` DECIMAL(4,1) NOT NULL DEFAULT 65.0;


-- Safe, minimal configuration rows (idempotent on the intended new database).
-- Leave all equipment ON/OFF times NULL: scheduler will not activate an unset schedule.
INSERT INTO `options` (`history`) SELECT 30 WHERE NOT EXISTS (SELECT 1 FROM `options`);
INSERT INTO `status`
 (`co2_status`,`o2_status`,`UV_status`,`heater_status`,`MasterL_status`,`PlantL_status`,`Backlight_status`,`fertilizer_pump_status`,`fertilizer_pump2_status`)
 SELECT 'unchecked','unchecked','unchecked','unchecked','unchecked','unchecked','unchecked','unchecked','unchecked'
 WHERE NOT EXISTS (SELECT 1 FROM `status`);

-- Sanity checks: expected exactly one row in each singleton and zero user/sample rows.
SELECT 'options' AS name, COUNT(*) AS rows_count FROM `options`
UNION ALL SELECT 'status', COUNT(*) FROM `status`
UNION ALL SELECT 'fertilizer_pump2', COUNT(*) FROM `fertilizer_pump2`
UNION ALL SELECT 'sensor_calibration', COUNT(*) FROM `sensor_calibration`
UNION ALL SELECT 'users', COUNT(*) FROM `users`
UNION ALL SELECT 'data', COUNT(*) FROM `data`
UNION ALL SELECT 'psutil', COUNT(*) FROM `psutil`;
