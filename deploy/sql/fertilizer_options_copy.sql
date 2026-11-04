-- OPTIONAL: run ONCE after fertilizer_options.sql while services are stopped.
-- Requires the old fertilizer_pump table to still exist.
-- Do NOT run this repeatedly after switching to the new code: it overwrites
-- pump settings with the old table's snapshot.
-- The queued/running pulse is retired during migration, NEVER replayed.
UPDATE `options` o
JOIN `fertilizer_pump` f ON f.`id`=1
SET o.`fertilizer_start_time`=f.`start_time`,
    o.`fertilizer_dose_ml`=f.`dose_ml`,
    o.`fertilizer_ml_per_second`=f.`ml_per_second`,
    o.`fertilizer_last_run_date`=f.`last_run_date`,
    o.`fertilizer_manual_request_id`=f.`manual_request_id`,
    o.`fertilizer_manual_processed_id`=f.`manual_request_id`,
    o.`fertilizer_manual_requested_at`=f.`manual_requested_at`,
    o.`fertilizer_manual_duration_seconds`=f.`manual_duration_seconds`,
    o.`fertilizer_manual_kind`=f.`manual_kind`,
    o.`fertilizer_calibration_saved_request_id`=f.`calibration_saved_request_id`,
    o.`fertilizer_pulse_request_id`=f.`pulse_request_id`,
    o.`fertilizer_pulse_kind`=f.`pulse_kind`,
    o.`fertilizer_pulse_state`=CASE
        WHEN f.`pulse_state` IN ('running','stop_requested') THEN 'interrupted'
        WHEN f.`pulse_state`='queued' THEN 'skipped'
        ELSE f.`pulse_state` END,
    o.`fertilizer_pulse_started_at`=f.`pulse_started_at`,
    o.`fertilizer_pulse_finished_at`=CASE
        WHEN f.`pulse_state` IN ('running','stop_requested','queued') THEN NOW(3)
        ELSE f.`pulse_finished_at` END,
    o.`fertilizer_pulse_duration_seconds`=f.`pulse_duration_seconds`;
