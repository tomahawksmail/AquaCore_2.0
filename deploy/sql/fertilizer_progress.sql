-- LEGACY ONLY: for historical installations using the old fertilizer_pump table.
-- Do NOT run on unified options/status installations.
-- Use fertilizer_options.sql; optionally copy the old data via fertilizer_options_copy.sql.
-- Pump worker progress/status tracking for real calibration progress UI.
-- Apply with aquacore.service and aquacore-relays.service STOPPED.
-- Existing installations: run fertilizer_pump.sql, fertilizer_manual.sql, fertilizer_ml.sql first.
-- No pending pulses are created, and dosing settings/calibration remain unchanged.
ALTER TABLE `fertilizer_pump`
  ADD COLUMN IF NOT EXISTS `pulse_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `pulse_kind` VARCHAR(16) NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS `pulse_state` VARCHAR(16) NOT NULL DEFAULT 'idle',
  ADD COLUMN IF NOT EXISTS `pulse_started_at` DATETIME(3) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `pulse_finished_at` DATETIME(3) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `pulse_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0;
-- Ignore any queued old manual request during the upgrade; do not re-dose.
UPDATE `fertilizer_pump`
   SET `manual_processed_id`=`manual_request_id`
 WHERE id=1 AND `manual_processed_id`<`manual_request_id`;
