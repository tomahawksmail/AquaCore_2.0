-- Run with aquacore.service and aquacore-relays.service STOPPED.
-- Requires the existing options singleton and status.fertilizer_pump_status.
-- Safe to rerun. New installations default to OFF and uncalibrated.
-- Does not read or drop the old fertilizer_pump table.
ALTER TABLE `options`
  ADD COLUMN IF NOT EXISTS `fertilizer_start_time` TIME NOT NULL DEFAULT '12:00:00',
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
