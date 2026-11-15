-- Explicit operator-requested TEMPORARY pH ESTIMATE.
-- A0=2.40V maps to pH ~7, with the slope from the SAVED 4.01 / 6.86
-- buffers; this is not a new physical electrode calibration.
-- Apply only if this provisional display is wanted. Does NOT change
-- ph401_voltage/ph686_voltage/ph918_voltage or existing measurement data.
ALTER TABLE sensor_calibration
  ADD COLUMN IF NOT EXISTS ph_provisional_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ph_provisional_neutral_v DOUBLE NOT NULL DEFAULT 2.40,
  ADD COLUMN IF NOT EXISTS ph_provisional_started_at DATETIME NULL;

-- This migration intentionally opts the user's single AquaCore setup
-- into the requested temporary pH=7 at 2.40V display.
UPDATE sensor_calibration
   SET ph_provisional_enabled=1,
       ph_provisional_neutral_v=2.40,
       ph_provisional_started_at=NOW()
 WHERE id=1 AND ph_provisional_enabled=0;
