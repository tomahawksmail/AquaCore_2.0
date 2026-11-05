-- Weekdays bitmask: Monday=bit0, Sunday=bit6. 127 preserves daily schedule.
ALTER TABLE `options` ADD COLUMN IF NOT EXISTS `fertilizer_weekdays` TINYINT UNSIGNED NOT NULL DEFAULT 127;
