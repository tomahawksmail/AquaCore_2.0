-- AquaCore fertilizer dosing pump (inactive until a nonzero duration is configured).
-- GPIO: gpiochip1 offset 233 (PH9 / Orange Pi header pin 26).
-- Execute once: sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_pump.sql
CREATE TABLE IF NOT EXISTS `fertilizer_pump` (
  `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  `start_time` TIME NOT NULL DEFAULT '12:00:00',
  `duration_seconds` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `last_run_date` DATE DEFAULT NULL,
  `manual_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `manual_processed_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `manual_requested_at` DATETIME DEFAULT NULL,
  `manual_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0,
  `dose_ml` DECIMAL(7,2) NOT NULL DEFAULT 0,
  `ml_per_second` DECIMAL(10,5) DEFAULT NULL,
  `manual_kind` VARCHAR(16) NOT NULL DEFAULT 'dose',
  `calibration_saved_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `pulse_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `pulse_kind` VARCHAR(16) NOT NULL DEFAULT '',
  `pulse_state` VARCHAR(16) NOT NULL DEFAULT 'idle',
  `pulse_started_at` DATETIME(3) DEFAULT NULL,
  `pulse_finished_at` DATETIME(3) DEFAULT NULL,
  `pulse_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO `fertilizer_pump` (`id`,`start_time`,`duration_seconds`)
VALUES (1,'12:00:00',0);
