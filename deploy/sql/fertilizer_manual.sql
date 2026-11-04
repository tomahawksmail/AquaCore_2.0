-- LEGACY ONLY: for historical installations using the old fertilizer_pump table.
-- Do NOT run on unified options/status installations.
-- Use fertilizer_options.sql; optionally copy the old data via fertilizer_options_copy.sql.
-- One-time migration for the fertilizer pump's manual "Dose now" request.
-- Run after deploy/sql/fertilizer_pump.sql (MariaDB 10.6+):
-- sudo mariadb _AquaCore_ < /opt/aquacore/deploy/sql/fertilizer_manual.sql
-- Defaults contain no pending request; this migration does not energize GPIO.
ALTER TABLE `fertilizer_pump`
  ADD COLUMN IF NOT EXISTS `manual_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `manual_processed_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `manual_requested_at` DATETIME NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `manual_duration_seconds` TINYINT UNSIGNED NOT NULL DEFAULT 0;
