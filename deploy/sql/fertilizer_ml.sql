-- Upgrade the existing fertilizer pump to volume-based dosing.
-- Apply with aquacore.service and aquacore-relays.service STOPPED.
-- Existing duration_seconds is retained for backward compatibility but IGNORED.
-- Fresh ml_per_second = NULL and dose_ml = 0 intentionally disable dosing.
ALTER TABLE `fertilizer_pump`
 ADD COLUMN IF NOT EXISTS `dose_ml` DECIMAL(7,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS `ml_per_second` DECIMAL(10,5) DEFAULT NULL,
 ADD COLUMN IF NOT EXISTS `manual_kind` VARCHAR(16) NOT NULL DEFAULT 'dose',
 ADD COLUMN IF NOT EXISTS `calibration_saved_request_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
 MODIFY COLUMN `manual_duration_seconds` DECIMAL(6,2) NOT NULL DEFAULT 0;
-- Discard any pre-upgrade pending requests. Do not fire delayed pumps.
UPDATE `fertilizer_pump`
   SET manual_processed_id=manual_request_id
 WHERE id=1 AND manual_processed_id<manual_request_id;
