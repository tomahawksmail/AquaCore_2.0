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
