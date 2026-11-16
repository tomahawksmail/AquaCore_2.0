-- ONE-TIME MIGRATION for a stopped existing AquaCore installation.
-- FIRST: back up MariaDB, stop collector, web, scheduler, Telegram and hardware
-- controller (ensure safe physical relay state). Update code before restarting.
-- Existing 3-point/temporary settings are intentionally replaced by the
-- user's supplied 2-buffer calibration, assumed at 25C.
-- Real historical water/temp/TDS data remains intact. ph_updated_at marks the
-- new calibration boundary for dashboard and Telegram (old pH hidden).
USE `_AquaCore_`;
ALTER TABLE `sensor_calibration`
 ADD COLUMN IF NOT EXISTS `ntc_enabled` TINYINT(1) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS `ntc_supply_v` DOUBLE NOT NULL DEFAULT 3.3,
 ADD COLUMN IF NOT EXISTS `temp_factor` DOUBLE NOT NULL DEFAULT 1.0,
 ADD COLUMN IF NOT EXISTS `temp_offset_c` DOUBLE NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS `temp_updated_at` DATETIME NULL,
 ADD COLUMN IF NOT EXISTS `tds_factor` DOUBLE NOT NULL DEFAULT 0.2626,
 ADD COLUMN IF NOT EXISTS `ph686_voltage` DOUBLE NULL,
 ADD COLUMN IF NOT EXISTS `ph401_voltage` DOUBLE NULL,
 ADD COLUMN IF NOT EXISTS `ph686_temp_c` DOUBLE NULL,
 ADD COLUMN IF NOT EXISTS `ph401_temp_c` DOUBLE NULL,
 ADD COLUMN IF NOT EXISTS `ph_updated_at` DATETIME NULL;

INSERT IGNORE INTO `sensor_calibration` (`id`) VALUES (1);
UPDATE `sensor_calibration`
   SET `ph686_voltage`=2.54, `ph401_voltage`=3.04,
       `ph686_temp_c`=25.0, `ph401_temp_c`=25.0,
       `ph_updated_at`=NOW()
 WHERE `id`=1;
ALTER TABLE `sensor_calibration`
 MODIFY COLUMN `ph686_voltage` DOUBLE NOT NULL DEFAULT 2.54,
 MODIFY COLUMN `ph401_voltage` DOUBLE NOT NULL DEFAULT 3.04,
 MODIFY COLUMN `ph686_temp_c` DOUBLE NOT NULL DEFAULT 25.0,
 MODIFY COLUMN `ph401_temp_c` DOUBLE NOT NULL DEFAULT 25.0;

-- Only fields no longer read or written by the updated code; MariaDB 10.6+.
ALTER TABLE `sensor_calibration`
 DROP COLUMN IF EXISTS `ph7_voltage`,
 DROP COLUMN IF EXISTS `ph4_voltage`,
 DROP COLUMN IF EXISTS `ph918_voltage`,
 DROP COLUMN IF EXISTS `ph918_reference`,
 DROP COLUMN IF EXISTS `ph918_temp_c`,
 DROP COLUMN IF EXISTS `ph401_reference`,
 DROP COLUMN IF EXISTS `ph686_reference`,
 DROP COLUMN IF EXISTS `ph_factor`,
 DROP COLUMN IF EXISTS `ph_provisional_enabled`,
 DROP COLUMN IF EXISTS `ph_provisional_neutral_v`,
 DROP COLUMN IF EXISTS `ph_provisional_started_at`;

SELECT id,ntc_enabled,temp_updated_at,ph686_voltage,ph401_voltage,
       ph686_temp_c,ph401_temp_c,ph_updated_at
  FROM sensor_calibration WHERE id=1;
