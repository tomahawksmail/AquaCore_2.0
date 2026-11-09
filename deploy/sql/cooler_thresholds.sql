-- AquaCore CPU fan thresholds (default behavior unchanged).
-- Run once before deploying the web and relay-worker changes.
ALTER TABLE `options`
  ADD COLUMN IF NOT EXISTS `cooler_on_c` DECIMAL(4,1) NOT NULL DEFAULT 70.0,
  ADD COLUMN IF NOT EXISTS `cooler_off_c` DECIMAL(4,1) NOT NULL DEFAULT 65.0;
